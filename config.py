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
from pathlib import Path

from dotenv import load_dotenv

# ── Step 1: Load .env file from project root ──────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent
_ENV_FILE = _PROJECT_ROOT / ".env"

if _ENV_FILE.exists():
    # override=True ensures .env values take priority over stale shell env
    load_dotenv(_ENV_FILE, override=True)

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
    """Attempt to read config from SSM Parameter Store. Fails silently.

    Has a 5-second overall timeout to prevent blocking app startup.
    """
    import threading

    def _do_load():
        try:
            import boto3

            profile = os.environ.get("AWS_PROFILE") or None
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
                    continue
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
            pass

    # Run with 5-second timeout — don't block app startup
    thread = threading.Thread(target=_do_load, daemon=True)
    thread.start()
    thread.join(timeout=5)
    if thread.is_alive():
        pass  # Timed out — SSM values not loaded, app continues with defaults


# Load SSM/CloudFormation values at import time.
# Has a 5-second timeout so it won't block indefinitely if credentials are expired.
# Skipped entirely when CLIMATE_RAG_SKIP_SSM=1 (e.g. in CI with dummy credentials).
if not os.environ.get("CLIMATE_RAG_SKIP_SSM"):
    _load_from_ssm()

# ── Ensure output directories exist ──────────────────────────────────────────
os.makedirs(os.environ.get("CHUNK_OUTPUT_DIR", "."), exist_ok=True)
os.makedirs(os.environ.get("CLIMATE_RAG_CHART_DIR", "."), exist_ok=True)
