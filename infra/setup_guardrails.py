"""
Provision Bedrock Guardrails for ClimateRAG production safety.

Creates a guardrail with:
  - Content filters: blocks hate, violence, sexual, misconduct content
  - Topic policy: denies non-climate topics (politics, medical advice, etc.)
  - Sensitive info: blocks PII in both input and output
  - Contextual grounding: detects hallucination and irrelevance
  - Word filters: blocks profanity

The guardrail ID and version are written to SSM Parameter Store so the
agent can apply them at runtime without hardcoding.

Usage:
    python infra/setup_guardrails.py

Prerequisites:
    - AWS credentials configured
    - Bedrock access enabled in us-east-1
"""

import json
import os
import sys
import time

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_REGION", "us-east-1")
GUARDRAIL_NAME = "ClimateRAG-ProductionGuardrail"


def log(msg):
    print(f"  {msg}", flush=True)


def section(title):
    print(f"\n{'=' * 60}", flush=True)
    print(f"  {title}", flush=True)
    print(f"{'=' * 60}", flush=True)


def find_existing_guardrail(client):
    """Check if guardrail already exists."""
    try:
        resp = client.list_guardrails()
        for g in resp.get("guardrails", []):
            if g["name"] == GUARDRAIL_NAME:
                return g["id"]
    except ClientError:
        pass
    return None


def create_guardrail(client):
    """Create the ClimateRAG production guardrail."""
    section("Bedrock Guardrail")

    # Check if already exists
    existing_id = find_existing_guardrail(client)
    if existing_id:
        log(f"Guardrail already exists: {existing_id}")
        # Get the latest version
        resp = client.get_guardrail(guardrailIdentifier=existing_id)
        version = resp.get("version", "DRAFT")
        return existing_id, version

    log(f"Creating guardrail: {GUARDRAIL_NAME}")

    resp = client.create_guardrail(
        name=GUARDRAIL_NAME,
        description=(
            "Production guardrail for ClimateRAG — filters harmful content, "
            "blocks off-topic queries, protects PII, and detects hallucination."
        ),
        # ── Topic Policy: Block non-climate topics ────────────────────
        topicPolicyConfig={
            "topicsConfig": [
                {
                    "name": "political-opinions",
                    "definition": (
                        "Political opinions, partisan commentary, election topics, "
                        "or policy advocacy unrelated to climate science."
                    ),
                    "examples": [
                        "Who should I vote for on climate policy?",
                        "Is climate change a political hoax?",
                        "Which party has the best environmental platform?",
                    ],
                    "type": "DENY",
                },
                {
                    "name": "medical-advice",
                    "definition": (
                        "Medical advice, health diagnoses, or treatment recommendations."
                    ),
                    "examples": [
                        "Can climate change cause cancer?",
                        "What medication should I take for heat stroke?",
                    ],
                    "type": "DENY",
                },
                {
                    "name": "financial-advice",
                    "definition": (
                        "Investment advice, stock picks, or financial planning."
                    ),
                    "examples": [
                        "Should I invest in solar energy stocks?",
                        "What climate stocks will go up?",
                    ],
                    "type": "DENY",
                },
                {
                    "name": "illegal-activities",
                    "definition": (
                        "Instructions for illegal activities, hacking, or causing harm."
                    ),
                    "examples": [
                        "How to hack a weather station",
                        "How to falsify climate data",
                    ],
                    "type": "DENY",
                },
            ]
        },
        # ── Content Policy: Filter harmful content ────────────────────
        contentPolicyConfig={
            "filtersConfig": [
                {"type": "SEXUAL", "inputStrength": "HIGH", "outputStrength": "HIGH"},
                {"type": "VIOLENCE", "inputStrength": "HIGH", "outputStrength": "HIGH"},
                {"type": "HATE", "inputStrength": "HIGH", "outputStrength": "HIGH"},
                {"type": "INSULTS", "inputStrength": "HIGH", "outputStrength": "HIGH"},
                {"type": "MISCONDUCT", "inputStrength": "HIGH", "outputStrength": "HIGH"},
                {"type": "PROMPT_ATTACK", "inputStrength": "HIGH", "outputStrength": "NONE"},
            ]
        },
        # ── Sensitive Information Policy: Block PII ───────────────────
        sensitiveInformationPolicyConfig={
            "piiEntitiesConfig": [
                {"type": "EMAIL", "action": "ANONYMIZE"},
                {"type": "PHONE", "action": "ANONYMIZE"},
                {"type": "US_SOCIAL_SECURITY_NUMBER", "action": "BLOCK"},
                {"type": "CREDIT_DEBIT_CARD_NUMBER", "action": "BLOCK"},
                {"type": "AWS_ACCESS_KEY", "action": "BLOCK"},
                {"type": "AWS_SECRET_KEY", "action": "BLOCK"},
            ]
        },
        # ── Word Policy: Block profanity ──────────────────────────────
        wordPolicyConfig={
            "managedWordListsConfig": [
                {"type": "PROFANITY"}
            ]
        },
        # ── Contextual Grounding: Detect hallucination ────────────────
        contextualGroundingPolicyConfig={
            "filtersConfig": [
                {
                    "type": "GROUNDING",
                    "threshold": 0.7,  # Block if grounding score < 70%
                },
                {
                    "type": "RELEVANCE",
                    "threshold": 0.7,  # Block if relevance score < 70%
                },
            ]
        },
        # ── Blocked messages ──────────────────────────────────────────
        blockedInputMessaging=(
            "I'm sorry, but I can only help with climate data analysis questions. "
            "Your query was blocked because it falls outside my area of expertise "
            "or contains content that violates safety policies."
        ),
        blockedOutputsMessaging=(
            "I apologize, but I cannot provide this response as it may contain "
            "inaccurate or inappropriate content. Please rephrase your question "
            "about climate data and I'll try again."
        ),
        # ── Tags (per provisioning policy) ────────────────────────────
        tags=[
            {"key": "Project", "value": "climate-rag"},
            {"key": "ManagedBy", "value": "kiro-cdk"},
            {"key": "Environment", "value": "dev"},
        ],
    )

    guardrail_id = resp["guardrailId"]
    log(f"Created guardrail: {guardrail_id}")

    # Create a versioned snapshot for production use
    log("Creating guardrail version...")
    version_resp = client.create_guardrail_version(
        guardrailIdentifier=guardrail_id,
        description="Initial production version for ClimateRAG",
    )
    version = version_resp["version"]
    log(f"Version created: {version}")

    return guardrail_id, version


def write_ssm_parameters(guardrail_id, version):
    """Write guardrail config to SSM for runtime consumption."""
    section("SSM Parameters")
    ssm = boto3.client("ssm", region_name=REGION)

    params = {
        "/climate-rag/guardrail-id": guardrail_id,
        "/climate-rag/guardrail-version": str(version),
    }

    for name, value in params.items():
        ssm.put_parameter(
            Name=name,
            Value=value,
            Type="String",
            Overwrite=True,
            Description="ClimateRAG Bedrock Guardrail config (auto-provisioned)",
        )
        log(f"{name} = {value}")


def main():
    print("\n🛡️  ClimateRAG — Bedrock Guardrails Setup")
    print(f"   Region: {REGION}\n")

    client = boto3.client("bedrock", region_name=REGION)

    guardrail_id, version = create_guardrail(client)
    write_ssm_parameters(guardrail_id, version)

    section("Done!")
    print(f"\n  Guardrail ID:      {guardrail_id}")
    print(f"  Guardrail Version: {version}")
    print(f"\n  Set environment variables:")
    print(f'    $env:CLIMATE_RAG_GUARDRAIL_ID = "{guardrail_id}"')
    print(f'    $env:CLIMATE_RAG_GUARDRAIL_VERSION = "{version}"')
    print(f"\n  The agent will auto-read these from SSM at startup.")


if __name__ == "__main__":
    main()
