"""
ClimateRAG — Centralized configuration loader.

Loads environment variables from .env file at project root, then
supplements missing values from AWS SSM Parameter Store (if credentials
are available).

Import this module at the top of any script that needs config:
    import config  # auto-loads .env and SSM values

All environment variables are then accessible via os.environ as usual.
"""

import os
import subprocess
import tempfile
from pathlib import Path

from dotenv import load_dotenv

# ── Step 1: Load .env file from project root ──────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent
_ENV_FILE = _PROJECT_ROOT / ".env"

if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=False)

# ── Step 1b: Auto-detect AWS profile if not already set ───────────────────────
# boto3 needs AWS_PROFILE or AWS_DEFAULT_PROFILE to use SSO credentials.
# If not set, find the first SSO profile from ~/.aws/config.
if not os.environ.get("AWS_PROFILE") and not os.environ.get("AWS_DEFAULT_PROFILE"):
    try:
        # Use 'aws configure list-profiles' to find available profiles
        result = subprocess.run(
            ["aws", "configure", "list-profiles"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            profiles = [p.strip() for p in result.stdout.strip().split("\n") if p.strip()]
            if profiles:
                # Use the first non-default profile (likely the SSO one)
                profile = profiles[0] if len(profiles) == 1 else next(
                    (p for p in profiles if p != "default"), profiles[0]
                )
                os.environ["AWS_PROFILE"] = profile
    except Exception:
        pass  # No AWS CLI available — boto3 will use default credential chain

# ── Step 2: Set sensible defaults for anything not in .env ────────────────────
_DEFAULTS = {
    "AWS_REGION": "us-east-1",
    "CLIMATE_RAG_BUCKET": "",
    "CLIMATE_RAG_MEMORY_ID": "",
    "CLIMATE_RAG_CODE_INTERPRETER_ID": "",
    "CLIMATE_RAG_GUARDRAIL_ID": "",
    "CLIMATE_RAG_GUARDRAIL_VERSION": "",
    "CLIMATE_RAG_MODEL": "us.anthropic.claude-sonnet-4-6",
    "CHUNK_OUTPUT_DIR": str(_PROJECT_ROOT / "data" / "chunks"),
    "CLIMATE_RAG_CHART_DIR": str(_PROJECT_ROOT / "data" / "charts"),
    "NOAA_CDO_TOKEN": "",
}

for key, default in _DEFAULTS.items():
    if not os.environ.get(key):
        os.environ[key] = default


# ── Step 3: Try to fill missing values from SSM (if AWS credentials work) ─────
def _load_from_ssm():
    """Attempt to read config from SSM Parameter Store. Fails silently."""
    try:
        import boto3

        # Create session with explicit profile if set
        profile = os.environ.get("AWS_PROFILE")
        session = boto3.Session(
            profile_name=profile,
            region_name=os.environ["AWS_REGION"],
        )
        ssm = session.client("ssm")

        ssm_params = {
            "CLIMATE_RAG_MEMORY_ID": "/climate-rag/memory-id",
            "CLIMATE_RAG_CODE_INTERPRETER_ID": "/climate-rag/code-interpreter-id",
            "CLIMATE_RAG_GUARDRAIL_ID": "/climate-rag/guardrail-id",
            "CLIMATE_RAG_GUARDRAIL_VERSION": "/climate-rag/guardrail-version",
        }

        for env_var, param_name in ssm_params.items():
            if os.environ.get(env_var):
                continue  # Already set from .env — don't override
            try:
                resp = ssm.get_parameter(Name=param_name)
                os.environ[env_var] = resp["Parameter"]["Value"]
            except Exception:
                pass

        # Try to get bucket from CloudFormation if not set
        if not os.environ.get("CLIMATE_RAG_BUCKET"):
            try:
                cfn = session.client("cloudformation")
                stacks = cfn.describe_stacks(StackName="ClimateRagDataStack")["Stacks"]
                for output in stacks[0].get("Outputs", []):
                    if output["OutputKey"] == "IndexBucketName":
                        os.environ["CLIMATE_RAG_BUCKET"] = output["OutputValue"]
            except Exception:
                pass

    except Exception:
        pass  # No credentials or boto3 not available — that's fine


_load_from_ssm()

# ── Ensure output directories exist ──────────────────────────────────────────
os.makedirs(os.environ["CHUNK_OUTPUT_DIR"], exist_ok=True)
os.makedirs(os.environ["CLIMATE_RAG_CHART_DIR"], exist_ok=True)
