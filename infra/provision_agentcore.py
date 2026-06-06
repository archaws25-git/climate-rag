"""
Provision AgentCore resources directly (bypassing CDK/CloudFormation).

This script creates Memory, Code Interpreter, and Gateway resources
using the boto3 API directly, with visible polling progress. It writes
the resulting IDs to SSM Parameter Store so the agent can read them.

Use this when CDK deployment times out due to slow Code Interpreter
activation (which can take 15-20 minutes in some regions/accounts).

Usage:
    cd climate-rag
    .venv\\Scripts\\Activate.ps1
    python infra/provision_agentcore.py

Prerequisites:
    - AWS credentials configured (aws sso login)
    - $env:AWS_PROFILE set if using SSO
    - ClimateRagComputeStack deployed (for Lambda ARNs and Gateway role)
"""

import os
import sys
import time

# Load all environment variables from .env + SSM
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config  # noqa: E402, F401

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_REGION", "us-east-1")


def log(msg):
    print(f"  {msg}", flush=True)


def section(title):
    print(f"\n{'=' * 60}", flush=True)
    print(f"  {title}", flush=True)
    print(f"{'=' * 60}", flush=True)


def wait_active(client, resource_type, resource_id, max_wait_minutes=30):
    """Poll until resource reaches ACTIVE, with visible countdown."""
    start = time.time()
    max_seconds = max_wait_minutes * 60
    attempt = 0

    while True:
        attempt += 1
        elapsed = int(time.time() - start)

        if resource_type == "memory":
            res = client.get_memory(memoryId=resource_id)
            status = res["memory"]["status"]
        elif resource_type == "code_interpreter":
            res = client.get_code_interpreter(codeInterpreterId=resource_id)
            status = res["status"]
        elif resource_type == "gateway":
            res = client.get_gateway(gatewayIdentifier=resource_id)
            status = res["status"]
        else:
            raise ValueError(f"Unknown resource_type: {resource_type}")

        log(f"[{elapsed:>4}s] Poll #{attempt}: {status}")

        if status in ("ACTIVE", "READY"):
            log(f"{status} after {elapsed}s")
            return True
        if status in ("FAILED", "DELETED", "DELETE_IN_PROGRESS"):
            raise RuntimeError(f"{resource_type} {resource_id} entered {status}")
        if elapsed > max_seconds:
            raise TimeoutError(
                f"{resource_type} {resource_id} did not reach ACTIVE "
                f"after {max_wait_minutes} minutes. Last status: {status}"
            )

        time.sleep(15)


def _find_memory_paginated(client, name):
    """Search all memories (paginated) for one with the given name."""
    kwargs = {}
    while True:
        resp = client.list_memories(**kwargs)
        for m in resp.get("memorySummaries", []):
            if m["name"] == name:
                return m["memoryId"]
        next_token = resp.get("nextToken")
        if not next_token:
            break
        kwargs["nextToken"] = next_token
    return None


def _find_code_interpreter_paginated(client, name):
    """Search all code interpreters (paginated) for one with the given name."""
    kwargs = {}
    while True:
        resp = client.list_code_interpreters(**kwargs)
        for ci in resp.get("codeInterpreterSummaries", []):
            if ci["name"] == name:
                return ci["codeInterpreterId"]
        next_token = resp.get("nextToken")
        if not next_token:
            break
        kwargs["nextToken"] = next_token
    return None


def _find_gateway_paginated(client, name):
    """Search all gateways (paginated) for one with the given name."""
    kwargs = {}
    while True:
        resp = client.list_gateways(**kwargs)
        for gw in resp.get("gatewaySummaries", []):
            if gw["name"] == name:
                return gw["gatewayId"]
        next_token = resp.get("nextToken")
        if not next_token:
            break
        kwargs["nextToken"] = next_token
    return None


def provision_memory(client):
    """Create or find existing ClimateRAGMemory."""
    section("AgentCore Memory")
    name = "ClimateRAGMemory"

    # Check if already exists (paginate through all results)
    mid = _find_memory_paginated(client, name)
    if mid:
        log(f"Already exists: {mid}")
        status = client.get_memory(memoryId=mid)["memory"]["status"]
        if status in ("ACTIVE", "READY"):
            return mid
        log(f"Status: {status} — waiting...")
        wait_active(client, "memory", mid)
        return mid

    log(f"Creating {name}...")
    try:
        res = client.create_memory(
            name=name,
            description="Climate research memory — researcher context and findings",
            eventExpiryDuration=30,
        )
    except (client.exceptions.ValidationException, ClientError) as e:
        # Memory already exists but wasn't found in list (pagination or timing)
        if "already exists" in str(e):
            log(f"Memory already exists (caught on create). Paginating full list...")
            # Paginate through all memories to find it
            mid = _find_memory_paginated(client, name)
            if mid:
                log(f"Found via pagination: {mid}")
                wait_active(client, "memory", mid)
                return mid
            # If still not found, the memory may be in a DELETED/DELETING state.
            # Just log and let the user know.
            raise RuntimeError(
                f"Memory '{name}' exists per API but cannot be found or is being deleted. "
                f"Wait a few minutes and try again, or use a different name."
            ) from e
        raise
    mid = res["memory"]["id"]
    log(f"Created: {mid}")
    wait_active(client, "memory", mid)
    return mid


def provision_code_interpreter(client):
    """Create or find existing ClimateChartInterpreter."""
    section("AgentCore Code Interpreter")
    name = "ClimateChartInterpreter"

    # Check if already exists (paginate through all results)
    cid = _find_code_interpreter_paginated(client, name)
    if cid:
        log(f"Already exists: {cid}")
        status = client.get_code_interpreter(codeInterpreterId=cid)["status"]
        if status in ("ACTIVE", "READY"):
            return cid
        log(f"Status: {status} — waiting...")
        wait_active(client, "code_interpreter", cid)
        return cid

    log(f"Creating {name}...")
    try:
        res = client.create_code_interpreter(
            name=name,
            description="Sandboxed Python for climate data chart generation",
            networkConfiguration={"networkMode": "PUBLIC"},
        )
    except client.exceptions.ValidationException as e:
        if "already exists" in str(e):
            log(f"Code Interpreter already exists (caught on create). Paginating...")
            cid = _find_code_interpreter_paginated(client, name)
            if cid:
                log(f"Found via pagination: {cid}")
                wait_active(client, "code_interpreter", cid, max_wait_minutes=30)
                return cid
            raise RuntimeError(
                f"Code Interpreter '{name}' exists per API but cannot be found. "
                f"Wait a few minutes and try again."
            ) from e
        raise
    cid = res["codeInterpreterId"]
    log(f"Created: {cid}")
    log("Code Interpreter can take 10-20 minutes to activate. Please wait...")
    wait_active(client, "code_interpreter", cid, max_wait_minutes=30)
    return cid


def provision_gateway(client):
    """Create or find existing ClimateDataGateway."""
    section("AgentCore Gateway")
    name = "ClimateDataGateway"

    # Get Gateway role ARN from ComputeStack
    cfn = boto3.client("cloudformation", region_name=REGION)
    try:
        outputs = cfn.describe_stacks(StackName="ClimateRagComputeStack")["Stacks"][0]["Outputs"]
        role_arn = next(o["OutputValue"] for o in outputs if o["OutputKey"] == "GatewayRoleArn")
        nasa_arn = next(o["OutputValue"] for o in outputs if o["OutputKey"] == "NasaLambdaArn")
        noaa_arn = next(o["OutputValue"] for o in outputs if o["OutputKey"] == "NoaaLambdaArn")
    except Exception as e:
        log(f"ERROR: Could not read ComputeStack outputs: {e}")
        log("Make sure ClimateRagComputeStack is deployed first.")
        sys.exit(1)

    # Check if already exists (paginate through all results)
    gwid = _find_gateway_paginated(client, name)
    if gwid:
        log(f"Already exists: {gwid}")
        status = client.get_gateway(gatewayIdentifier=gwid)["status"]
        if status in ("ACTIVE", "READY"):
            return gwid
        log(f"Status: {status} — waiting...")
        wait_active(client, "gateway", gwid)
        return gwid

    log(f"Creating {name}...")
    res = client.create_gateway(
        name=name,
        description="Gateway for climate data APIs (NASA POWER, NOAA NCEI)",
        protocolType="MCP",
        authorizerType="NONE",
        # authorizerConfiguration omitted — not required when authorizerType=NONE
        # Passing {} triggers boto3 tagged union validation error.
        roleArn=role_arn,
        protocolConfiguration={"mcp": {"searchType": "SEMANTIC"}},
        exceptionLevel="DEBUG",
    )
    gwid = res["gatewayId"]
    log(f"Created: {gwid}")
    wait_active(client, "gateway", gwid)

    # Create targets
    _create_targets(client, gwid, nasa_arn, noaa_arn)
    return gwid


def _create_targets(client, gw_id, nasa_arn, noaa_arn):
    """Create Lambda targets on the Gateway."""
    existing = {
        t["name"]
        for t in client.list_gateway_targets(gatewayIdentifier=gw_id).get("gatewayTargetSummaries", [])
    }

    if "nasa-power-proxy" not in existing:
        client.create_gateway_target(
            gatewayIdentifier=gw_id,
            name="nasa-power-proxy",
            targetConfiguration={"mcp": {"lambda": {
                "lambdaArn": nasa_arn,
                "toolSchema": {"inlinePayload": [{
                    "name": "nasa_power_query",
                    "description": "Query NASA POWER API for climate data",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "latitude": {"type": "number"},
                            "longitude": {"type": "number"},
                            "start": {"type": "string"},
                            "end": {"type": "string"},
                            "parameters": {"type": "string"},
                        },
                        "required": ["latitude", "longitude", "start", "end"],
                    },
                }]},
            }}},
            credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
        )
        log("Created target: nasa-power-proxy")
    else:
        log("Target exists: nasa-power-proxy")

    if "noaa-ncei-proxy" not in existing:
        client.create_gateway_target(
            gatewayIdentifier=gw_id,
            name="noaa-ncei-proxy",
            targetConfiguration={"mcp": {"lambda": {
                "lambdaArn": noaa_arn,
                "toolSchema": {"inlinePayload": [{
                    "name": "noaa_ncei_query",
                    "description": "Query NOAA NCEI for historical climate observations",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "dataset": {"type": "string"},
                            "stations": {"type": "string"},
                            "startDate": {"type": "string"},
                            "endDate": {"type": "string"},
                            "dataTypes": {"type": "string"},
                        },
                        "required": ["dataset", "startDate", "endDate"],
                    },
                }]},
            }}},
            credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
        )
        log("Created target: noaa-ncei-proxy")
    else:
        log("Target exists: noaa-ncei-proxy")


def write_ssm_parameters(memory_id, code_interpreter_id, gateway_id):
    """Write resource IDs to SSM Parameter Store."""
    section("SSM Parameters")
    ssm = boto3.client("ssm", region_name=REGION)

    params = {
        "/climate-rag/memory-id": memory_id,
        "/climate-rag/code-interpreter-id": code_interpreter_id,
        "/climate-rag/gateway-id": gateway_id,
    }

    for name, value in params.items():
        ssm.put_parameter(
            Name=name,
            Value=value,
            Type="String",
            Overwrite=True,
            Description=f"ClimateRAG AgentCore resource ID (auto-provisioned)",
        )
        log(f"{name} = {value}")


def main():
    print("\n🌍 ClimateRAG — AgentCore Resource Provisioner")
    print(f"   Region: {REGION}\n")

    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    memory_id = provision_memory(client)
    code_interpreter_id = provision_code_interpreter(client)
    gateway_id = provision_gateway(client)
    write_ssm_parameters(memory_id, code_interpreter_id, gateway_id)

    section("Done!")
    print(f"\n  Memory ID:            {memory_id}")
    print(f"  Code Interpreter ID:  {code_interpreter_id}")
    print(f"  Gateway ID:           {gateway_id}")
    print(f"\n  Set environment variables:")
    print(f'    $env:CLIMATE_RAG_MEMORY_ID = "{memory_id}"')
    print(f'    $env:CLIMATE_RAG_CODE_INTERPRETER_ID = "{code_interpreter_id}"')
    print(f"\n  Then run: streamlit run ui/app.py\n")


if __name__ == "__main__":
    main()
