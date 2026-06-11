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
    python infra/provision_agentcore.py            # provision
    python infra/provision_agentcore.py --teardown # destroy all resources

Prerequisites:
    - AWS credentials configured (aws sso login)
    - $env:AWS_PROFILE set if using SSO
    - ClimateRagComputeStack deployed (for Lambda ARNs and Gateway role)
"""

import argparse
import os
import sys
import time

# Load all environment variables from .env + SSM
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config  # noqa: E402, F401

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

REGION = os.environ.get("AWS_REGION", "us-east-1")

# Resource names created by this script
MEMORY_NAME = os.environ.get("CLIMATE_RAG_MEMORY_NAME", "ClimateRAGMemory")
CODE_INTERPRETER_NAME = "ClimateChartInterpreter"
GATEWAY_NAME = "ClimateDataGateway"

# SSM parameters written by this script
SSM_PARAMETERS = [
    "/climate-rag/memory-id",
    "/climate-rag/code-interpreter-id",
    "/climate-rag/gateway-id",
]


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
    """Find memory by name using multiple strategies.

    AgentCore's list_memories API returns results under 'memories' key
    and does NOT include the name field. We must get_memory each one
    to check the name, or fall back to SSM/CloudFormation.
    """
    # Strategy 1: list_memories and check each via get_memory
    kwargs = {}
    while True:
        resp = client.list_memories(**kwargs)
        # API returns under 'memories' key (not 'memorySummaries')
        for m in resp.get("memories", resp.get("memorySummaries", [])):
            mid = m.get("id", m.get("memoryId", ""))
            if not mid:
                continue
            # list response may not include name — verify via get_memory
            if m.get("name") == name:
                return mid
            try:
                detail = client.get_memory(memoryId=mid)
                if detail["memory"].get("name") == name:
                    return mid
            except ClientError:
                continue
        next_token = resp.get("nextToken")
        if not next_token:
            break
        kwargs["nextToken"] = next_token

    # Strategy 2: Check SSM for a previously-stored ID and verify it's alive
    ssm = boto3.client("ssm", region_name=REGION)
    try:
        resp = ssm.get_parameter(Name="/climate-rag/memory-id")
        ssm_id = resp["Parameter"]["Value"]
        if ssm_id:
            try:
                res = client.get_memory(memoryId=ssm_id)
                if res["memory"].get("name") == name:
                    return ssm_id
            except ClientError:
                pass
    except ClientError:
        pass

    # Strategy 3: Check CloudFormation outputs (AgentCore stack)
    try:
        cfn = boto3.client("cloudformation", region_name=REGION)
        stacks = cfn.describe_stacks(StackName="ClimateRagAgentCoreStack")["Stacks"]
        for output in stacks[0].get("Outputs", []):
            if output["OutputKey"] == "MemoryId":
                cfn_id = output["OutputValue"]
                try:
                    res = client.get_memory(memoryId=cfn_id)
                    if res["memory"].get("name") == name:
                        return cfn_id
                except ClientError:
                    pass
    except ClientError:
        pass

    return None


def _find_code_interpreter_paginated(client, name):
    """Find code interpreter by name using multiple strategies.

    Same visibility gap workaround as _find_memory_paginated.
    """
    # Strategy 1: list_code_interpreters
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

    # Strategy 2: Check SSM for a previously-stored ID and verify
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        resp = ssm.get_parameter(Name="/climate-rag/code-interpreter-id")
        ssm_id = resp["Parameter"]["Value"]
        if ssm_id:
            try:
                res = client.get_code_interpreter(codeInterpreterId=ssm_id)
                if res.get("name") == name:
                    return ssm_id
            except ClientError:
                pass
    except ClientError:
        pass

    return None


def _find_gateway_paginated(client, name):
    """Find gateway by name using multiple strategies.

    AgentCore's list_gateways API returns results under 'items' key.
    """
    # Strategy 1: list_gateways (case-insensitive name match)
    kwargs = {}
    while True:
        resp = client.list_gateways(**kwargs)
        # API returns under 'items' key (not 'gatewaySummaries')
        for gw in resp.get("items", resp.get("gatewaySummaries", [])):
            if gw.get("name", "").lower() == name.lower():
                return gw["gatewayId"]
        next_token = resp.get("nextToken")
        if not next_token:
            break
        kwargs["nextToken"] = next_token

    # Strategy 2: Check SSM for a previously-stored ID and verify
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        resp = ssm.get_parameter(Name="/climate-rag/gateway-id")
        ssm_id = resp["Parameter"]["Value"]
        if ssm_id:
            try:
                res = client.get_gateway(gatewayIdentifier=ssm_id)
                if res.get("name", "").lower() == name.lower():
                    return ssm_id
            except ClientError:
                pass
    except ClientError:
        pass

    # Strategy 3: CloudFormation outputs
    try:
        cfn = boto3.client("cloudformation", region_name=REGION)
        for stack_name in ("ClimateRagAgentCoreStack", "ClimateRagComputeStack"):
            try:
                stacks = cfn.describe_stacks(StackName=stack_name)["Stacks"]
                for output in stacks[0].get("Outputs", []):
                    if output["OutputKey"] == "GatewayId":
                        cfn_id = output["OutputValue"]
                        try:
                            res = client.get_gateway(gatewayIdentifier=cfn_id)
                            if res.get("name", "").lower() == name.lower():
                                return cfn_id
                        except ClientError:
                            pass
            except ClientError:
                pass
    except ClientError:
        pass

    return None


def provision_memory(client):
    """Create or find existing ClimateRAGMemory."""
    section("AgentCore Memory")
    name = MEMORY_NAME

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
        if "already exists" in str(e):
            log("Memory name is reserved (phantom state from prior deletion).")
            # Try to find it via pagination one more time
            mid = _find_memory_paginated(client, name)
            if mid:
                log(f"Found via pagination: {mid}")
                status = client.get_memory(memoryId=mid)["memory"]["status"]
                if status in ("DELETE_IN_PROGRESS", "DELETING"):
                    log(f"Memory is being deleted (status: {status}). Waiting...")
                    _wait_deleted(client, "memory", mid)
                    log("Deletion complete. Retrying creation...")
                    time.sleep(5)
                    return provision_memory(client)
                wait_active(client, "memory", mid)
                return mid

            # Phantom state: name reserved but not listable/gettable.
            # Use a versioned name to work around it.
            alt_name = f"{name}V2"
            log(f"Using alternate name: {alt_name}")
            # Check if the alternate already exists
            alt_mid = _find_memory_paginated(client, alt_name)
            if alt_mid:
                log(f"Alternate already exists: {alt_mid}")
                wait_active(client, "memory", alt_mid)
                return alt_mid
            try:
                res = client.create_memory(
                    name=alt_name,
                    description="Climate research memory — researcher context and findings",
                    eventExpiryDuration=30,
                )
                mid = res["memory"]["id"]
                log(f"Created with alternate name: {mid}")
                wait_active(client, "memory", mid)
                return mid
            except (client.exceptions.ValidationException, ClientError) as retry_err:
                raise RuntimeError(
                    f"Cannot create memory. Both '{name}' and '{alt_name}' are "
                    f"unavailable. Wait 10-15 minutes for the backend to clear "
                    f"the phantom state, then try again."
                ) from retry_err
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
            log("Code Interpreter already exists (caught on create). Paginating...")
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
    try:
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
    except (ClientError, Exception) as e:
        if "already exists" in str(e) or "ConflictException" in str(type(e).__name__) or "Conflict" in str(e):
            log("Gateway already exists (caught on create). Searching...")
            gwid = _find_gateway_paginated(client, name)
            if gwid:
                log(f"Found: {gwid}")
                wait_active(client, "gateway", gwid)
                _create_targets(client, gwid, nasa_arn, noaa_arn)
                return gwid

            # Last resort: list ALL gateways and match by name (case-insensitive)
            log("Standard lookup failed. Brute-force listing all gateways...")
            all_kwargs = {}
            while True:
                resp = client.list_gateways(**all_kwargs)
                for gw in resp.get("gatewaySummaries", []):
                    log(f"  Visible: {gw['name']} ({gw['gatewayId']})")
                    if gw["name"].lower() == name.lower():
                        gwid = gw["gatewayId"]
                        wait_active(client, "gateway", gwid)
                        _create_targets(client, gwid, nasa_arn, noaa_arn)
                        return gwid
                nxt = resp.get("nextToken")
                if not nxt:
                    break
                all_kwargs["nextToken"] = nxt

            # If we STILL can't find it, ask the user for the ID
            log("")
            log("ERROR: Gateway exists but cannot be found via any lookup strategy.")
            log("The AgentCore list API has visibility gaps for older resources.")
            log("")
            log("Please provide the gateway ID manually. You can find it in the")
            log("AWS Console under Bedrock > AgentCore > Gateways.")
            log("")
            manual_id = input("  Enter gateway ID (e.g. climatedatagateway-r15lmzdgpz): ").strip()
            if manual_id:
                try:
                    client.get_gateway(gatewayIdentifier=manual_id)
                    log(f"Verified: {manual_id}")
                    # Store in SSM so we never have to ask again
                    ssm = boto3.client("ssm", region_name=REGION)
                    ssm.put_parameter(
                        Name="/climate-rag/gateway-id",
                        Value=manual_id,
                        Type="String",
                        Overwrite=True,
                    )
                    _create_targets(client, manual_id, nasa_arn, noaa_arn)
                    return manual_id
                except ClientError as verify_err:
                    raise RuntimeError(
                        f"Could not verify gateway ID '{manual_id}': {verify_err}"
                    ) from e
            raise RuntimeError(
                f"Gateway '{name}' exists but cannot be found. "
                f"Provide the ID via: python infra/provision_agentcore.py "
                f"--gateway-id <id>"
            ) from e
        raise
    gwid = res["gatewayId"]
    log(f"Created: {gwid}")
    wait_active(client, "gateway", gwid)

    # Create targets
    _create_targets(client, gwid, nasa_arn, noaa_arn)
    return gwid


def _create_targets(client, gw_id, nasa_arn, noaa_arn):
    """Create Lambda targets on the Gateway."""
    resp = client.list_gateway_targets(gatewayIdentifier=gw_id)
    # API returns under 'items' key (not 'gatewayTargetSummaries')
    existing = {
        t["name"]
        for t in resp.get("items", resp.get("gatewayTargetSummaries", []))
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
            Description="ClimateRAG AgentCore resource ID (auto-provisioned)",
        )
        log(f"{name} = {value}")


def main():
    """Entry point — provision or teardown based on CLI flags."""
    parser = argparse.ArgumentParser(
        description="Provision or teardown AgentCore resources for ClimateRAG."
    )
    parser.add_argument(
        "--teardown",
        action="store_true",
        help="Destroy all AgentCore resources created by this script.",
    )
    parser.add_argument(
        "--memory-id",
        help="Provide memory ID directly (skips create, useful when list API fails).",
    )
    parser.add_argument(
        "--code-interpreter-id",
        help="Provide code interpreter ID directly (skips create).",
    )
    parser.add_argument(
        "--gateway-id",
        help="Provide gateway ID directly (skips create).",
    )
    args = parser.parse_args()

    if args.teardown:
        teardown(args)
    else:
        provision(args)


def provision(args):
    """Create all AgentCore resources and write IDs to SSM."""
    print("\n🌍 ClimateRAG — AgentCore Resource Provisioner")
    print(f"   Region: {REGION}\n")

    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    # Use provided IDs or provision new resources
    if args.memory_id:
        memory_id = args.memory_id
        log(f"Using provided memory ID: {memory_id}")
        try:
            res = client.get_memory(memoryId=memory_id)
            log(f"  Verified: {res['memory']['name']} ({res['memory']['status']})")
        except ClientError as e:
            log(f"  WARNING: Could not verify memory: {e}")
    else:
        memory_id = provision_memory(client)

    if args.code_interpreter_id:
        code_interpreter_id = args.code_interpreter_id
        log(f"Using provided code interpreter ID: {code_interpreter_id}")
        try:
            res = client.get_code_interpreter(codeInterpreterId=code_interpreter_id)
            log(f"  Verified: {res['name']} ({res['status']})")
        except ClientError as e:
            log(f"  WARNING: Could not verify code interpreter: {e}")
    else:
        code_interpreter_id = provision_code_interpreter(client)

    if args.gateway_id:
        gateway_id = args.gateway_id
        log(f"Using provided gateway ID: {gateway_id}")
        try:
            res = client.get_gateway(gatewayIdentifier=gateway_id)
            log(f"  Verified: {res['name']} ({res['status']})")
        except ClientError as e:
            log(f"  WARNING: Could not verify gateway: {e}")
    else:
        gateway_id = provision_gateway(client)

    write_ssm_parameters(memory_id, code_interpreter_id, gateway_id)

    section("Done!")
    print(f"\n  Memory ID:            {memory_id}")
    print(f"  Code Interpreter ID:  {code_interpreter_id}")
    print(f"  Gateway ID:           {gateway_id}")
    print(f'    $env:CLIMATE_RAG_MEMORY_ID = "{memory_id}"')
    print(f'    $env:CLIMATE_RAG_CODE_INTERPRETER_ID = "{code_interpreter_id}"')
    print("  Then run: streamlit run ui/app.py\n")


def teardown(args):
    """Destroy all AgentCore resources created by this script.

    Deletion order matters:
      1. Gateway targets (must be removed before gateway)
      2. Gateway
      3. Code Interpreter
      4. Memory
      5. SSM Parameters
    """
    print("\n🌍 ClimateRAG — AgentCore Resource Teardown")
    print(f"   Region: {REGION}")
    print("   This will DELETE: Memory, Code Interpreter, Gateway, SSM params\n")

    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    # ── 1. Delete Gateway (targets first) ─────────────────────────
    _teardown_gateway(client, override_id=args.gateway_id)

    # ── 2. Delete Code Interpreter ────────────────────────────────
    _teardown_code_interpreter(client, override_id=args.code_interpreter_id)

    # ── 3. Delete Memory ──────────────────────────────────────────
    _teardown_memory(client, override_id=args.memory_id)

    # ── 4. Delete SSM Parameters ──────────────────────────────────
    _teardown_ssm_parameters()

    section("Teardown Complete!")
    print("  All AgentCore resources have been removed.\n")


def _teardown_gateway(client, override_id=None):
    """Find and delete the ClimateDataGateway and its targets.

    Deletes all gateway targets first, then polls (up to 60s) until
    the targets are fully removed before deleting the gateway itself.
    This prevents ConflictException errors caused by deleting a gateway
    while its targets are still in a DELETING state.
    """
    section(f"Deleting Gateway: {GATEWAY_NAME}")

    gwid = override_id or _find_gateway_paginated(client, GATEWAY_NAME)
    if not gwid:
        log("Not found — skipping.")
        return

    log(f"Found: {gwid}")

    # Delete all targets first
    try:
        resp = client.list_gateway_targets(gatewayIdentifier=gwid)
        # API returns under 'items' key (not 'gatewayTargetSummaries')
        targets = resp.get("items", resp.get("gatewayTargetSummaries", []))
        for target in targets:
            target_id = target.get("targetId", target.get("name", ""))
            target_name = target.get("name", target_id)
            log(f"Deleting target: {target_name} (id: {target_id})...")
            try:
                client.delete_gateway_target(
                    gatewayIdentifier=gwid,
                    targetId=target_id,
                )
                log(f"  Delete initiated: {target_name}")
            except ClientError as e:
                if "ResourceNotFoundException" in str(e):
                    log(f"  Already deleted: {target_name}")
                else:
                    log(f"  Warning: Could not delete target {target_name}: {e}")

        # Wait for all targets to be fully removed before deleting the gateway
        if targets:
            import time as _time
            log("Waiting for targets to be fully removed...")
            max_wait = 60  # seconds
            start = _time.time()
            while _time.time() - start < max_wait:
                resp = client.list_gateway_targets(gatewayIdentifier=gwid)
                remaining = resp.get("items", resp.get("gatewayTargetSummaries", []))
                if not remaining:
                    log("  All targets removed.")
                    break
                log(f"  {len(remaining)} target(s) still deleting...")
                _time.sleep(5)
            else:
                log(f"  Warning: Timed out waiting for target deletion after {max_wait}s")
    except ClientError as e:
        log(f"Warning: Could not list targets: {e}")

    # Delete the gateway
    log(f"Deleting gateway {gwid}...")
    try:
        client.delete_gateway(gatewayIdentifier=gwid)
        log("Delete initiated. Waiting for removal...")
        _wait_deleted(client, "gateway", gwid)
    except ClientError as e:
        if "ResourceNotFoundException" in str(e):
            log("Already deleted.")
        else:
            log(f"Warning: {e}")


def _teardown_code_interpreter(client, override_id=None):
    """Find and delete the ClimateChartInterpreter."""
    section(f"Deleting Code Interpreter: {CODE_INTERPRETER_NAME}")

    cid = override_id or _find_code_interpreter_paginated(client, CODE_INTERPRETER_NAME)
    if not cid:
        log("Not found — skipping.")
        return

    log(f"Found: {cid}")
    try:
        client.delete_code_interpreter(codeInterpreterId=cid)
        log("Delete initiated. Waiting for removal...")
        _wait_deleted(client, "code_interpreter", cid)
    except ClientError as e:
        if "ResourceNotFoundException" in str(e):
            log("Already deleted.")
        else:
            log(f"Warning: {e}")


def _teardown_memory(client, override_id=None):
    """Find and delete the ClimateRAGMemory."""
    section(f"Deleting Memory: {MEMORY_NAME}")

    mid = override_id or _find_memory_paginated(client, MEMORY_NAME)
    if not mid:
        log("Not found — skipping.")
        return

    log(f"Found: {mid}")
    try:
        client.delete_memory(memoryId=mid)
        log("Delete initiated. Waiting for removal...")
        _wait_deleted(client, "memory", mid)
    except ClientError as e:
        if "ResourceNotFoundException" in str(e):
            log("Already deleted.")
        else:
            log(f"Warning: {e}")


def _teardown_ssm_parameters():
    """Delete all SSM parameters created by this script."""
    section("Deleting SSM Parameters")
    ssm = boto3.client("ssm", region_name=REGION)

    for param_name in SSM_PARAMETERS:
        try:
            ssm.delete_parameter(Name=param_name)
            log(f"Deleted: {param_name}")
        except ClientError as e:
            if "ParameterNotFound" in str(e):
                log(f"Not found: {param_name} — skipping.")
            else:
                log(f"Warning: Could not delete {param_name}: {e}")


def _wait_deleted(client, resource_type, resource_id, max_wait_minutes=10):
    """Poll until resource is gone or in DELETED state."""
    start = time.time()
    max_seconds = max_wait_minutes * 60

    while True:
        elapsed = int(time.time() - start)
        try:
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
                return

            if status in ("DELETED", "FAILED"):
                log(f"  Confirmed: {status} after {elapsed}s")
                return

            log(f"  [{elapsed:>4}s] Status: {status}")

            if elapsed > max_seconds:
                log(f"  Timed out waiting for deletion after {max_wait_minutes}min.")
                return

            time.sleep(10)

        except ClientError as e:
            if "ResourceNotFoundException" in str(e) or "NotFound" in str(e):
                log(f"  Confirmed deleted after {elapsed}s")
                return
            raise


if __name__ == "__main__":
    main()
