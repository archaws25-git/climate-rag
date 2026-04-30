"""
AgentCore Custom Resource Handler
══════════════════════════════════
Replaces tf_agentcore.py as the authoritative provisioning logic for
AgentCore resources that have no native CloudFormation / CDK support:
  - AgentCore Memory
  - AgentCore Code Interpreter
  - AgentCore Gateway (+ Gateway Targets)

Architecture
────────────
A single Lambda function handles all three resource types via a
ResourceType discriminator in ResourceProperties.  This mirrors the
subcommand dispatch pattern in tf_agentcore.py but replaces:

  CLI pattern (removed)            CDK/CFN pattern (added)
  ────────────────────────────     ──────────────────────────────────
  argparse subcommands             event["ResourceType"] dispatcher
  open(args.out, "w").write(id)    return PhysicalResourceId + Data{}
  sys.exit(1)                      raise exception (CFN marks FAILED)
  print() to stdout                logger.info/error (CloudWatch Logs)
  time.sleep() fixed delay         exponential backoff retry loop

CloudFormation Lifecycle Events
────────────────────────────────
  Create  → provision the resource, wait for ACTIVE, return its ID
  Update  → for Memory/CI: passthrough (no mutable fields in scope)
            for Gateway: reconcile targets (add missing, leave existing)
  Delete  → deprovision the resource; ResourceNotFoundException is
            treated as success (idempotent teardown)

Response contract (CloudFormation Custom Resource protocol):
  {
    "PhysicalResourceId": "<resource-id>",   # used on Update/Delete
    "Data": {
        "MemoryId":          "...",           # Memory only
        "CodeInterpreterId": "...",           # Code Interpreter only
        "GatewayId":         "...",           # Gateway only
    }
  }
  Raising any exception → CloudFormation marks the resource FAILED and
  rolls back the stack automatically.
"""

import json
import logging
import time

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = "us-east-1"


def get_client():
    return boto3.client("bedrock-agentcore-control", region_name=REGION)


# ── CloudFormation entry point ────────────────────────────────────────────────

def handler(event, context):
    logger.info("Event: %s", json.dumps(event))

    resource_type = event["ResourceProperties"]["ResourceType"]
    request_type  = event["RequestType"]          # Create | Update | Delete
    physical_id   = event.get("PhysicalResourceId", "PENDING")
    props         = event["ResourceProperties"]

    dispatch = {
        "Memory":          _handle_memory,
        "CodeInterpreter": _handle_code_interpreter,
        "Gateway":         _handle_gateway,
    }

    if resource_type not in dispatch:
        raise ValueError(f"Unknown ResourceType: {resource_type!r}")

    result = dispatch[resource_type](request_type, physical_id, props)
    logger.info("Result: %s", json.dumps(result))
    return result


# ── Shared helpers ────────────────────────────────────────────────────────────

def _wait_active(poll_fn, resource_id: str, label: str, timeout: int = 600) -> None:
    """
    Poll until a resource reaches ACTIVE status.

    Uses exponential backoff (10s → 20s → 40s … capped at 60s) to avoid
    hammering the control-plane API during the ~3-minute provisioning window
    that AgentCore Memory and Code Interpreter require.

    Raises RuntimeError if the resource enters FAILED/DELETED or if the
    timeout is exceeded — both cause CloudFormation to roll back the stack.
    """
    delay = 10
    elapsed = 0
    while elapsed < timeout:
        status = poll_fn(resource_id)
        logger.info("%s %s status: %s", label, resource_id, status)
        if status == "ACTIVE":
            return
        if status in ("FAILED", "DELETED", "DELETE_IN_PROGRESS"):
            raise RuntimeError(f"{label} {resource_id} entered terminal state: {status}")
        time.sleep(delay)
        elapsed += delay
        delay = min(delay * 2, 60)   # exponential backoff, cap at 60s

    raise TimeoutError(f"{label} {resource_id} did not reach ACTIVE within {timeout}s")


def _cfn_response(physical_id: str, data: dict) -> dict:
    return {"PhysicalResourceId": physical_id, "Data": data}


def _extract_memory_id(resp: dict) -> str:
    return resp.get("memoryId") or resp.get("memory", {}).get("memoryId")


def _extract_memory_status(resp: dict) -> str:
    return resp.get("status") or resp.get("memory", {}).get("status")


def _extract_code_interpreter_id(resp: dict) -> str:
    return resp.get("codeInterpreterId") or resp.get("codeInterpreter", {}).get("codeInterpreterId")


def _extract_code_interpreter_status(resp: dict) -> str:
    return resp.get("status") or resp.get("codeInterpreter", {}).get("status")


# ── Memory ────────────────────────────────────────────────────────────────────

def _handle_memory(request_type: str, physical_id: str, props: dict) -> dict:
    client = get_client()
    name = props["Name"]

    if request_type == "Create":
        # Idempotent: if a Memory with this name already exists, reuse it.
        existing = [
            m for m in client.list_memories().get("memorySummaries", [])
            if m["name"] == name
        ]
        if existing:
            memory_id = existing[0]["memoryId"]
            logger.info("Memory already exists — reusing: %s", memory_id)
        else:
            resp = client.create_memory(
                name=name,
                description=props.get("Description", "ClimateRAG research memory"),
                eventExpiryDuration=int(props.get("EventExpiryDays", 30)),
                memoryStrategies=[{
                    "semanticMemoryStrategy": {
                        "name": "climateSemanticMemory",
                        "namespaces": [
                            "/strategies/{memoryStrategyId}/actors/{actorId}/"
                        ],
                    }
                }],
            )
            memory_id = _extract_memory_id(resp)
            logger.info("Created Memory: %s", memory_id)

        _wait_active(
            lambda mid: _extract_memory_status(
                client.get_memory(memoryId=mid)
            ),
            memory_id,
            "Memory",
        )
        return _cfn_response(memory_id, {"MemoryId": memory_id})

    if request_type == "Update":
        # Memory has no mutable fields in scope for this project.
        # Return existing physical ID unchanged.
        logger.info("Memory Update — no-op, returning existing ID: %s", physical_id)
        return _cfn_response(physical_id, {"MemoryId": physical_id})

    if request_type == "Delete":
        try:
            client.delete_memory(memoryId=physical_id)
            logger.info("Deleted Memory: %s", physical_id)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                logger.info("Memory %s already deleted — skipping", physical_id)
            else:
                raise
        return _cfn_response(physical_id, {})

    raise ValueError(f"Unknown RequestType: {request_type!r}")


# ── Code Interpreter ──────────────────────────────────────────────────────────

def _handle_code_interpreter(request_type: str, physical_id: str, props: dict) -> dict:
    client = get_client()
    name = props["Name"]

    if request_type == "Create":
        existing = [
            c for c in client.list_code_interpreters().get("codeInterpreterSummaries", [])
            if c["name"] == name
        ]
        if existing:
            ci_id = existing[0]["codeInterpreterId"]
            logger.info("Code Interpreter already exists — reusing: %s", ci_id)
        else:
            resp = client.create_code_interpreter(
                name=name,
                description=props.get(
                    "Description", "Sandboxed Python for climate data chart generation"
                ),
                networkConfiguration={"networkMode": "PUBLIC"},
            )
            ci_id = _extract_code_interpreter_id(resp)
            logger.info("Created Code Interpreter: %s", ci_id)

        _wait_active(
            lambda cid: _extract_code_interpreter_status(
                client.get_code_interpreter(codeInterpreterId=cid)
            ),
            ci_id,
            "CodeInterpreter",
        )
        return _cfn_response(ci_id, {"CodeInterpreterId": ci_id})

    if request_type == "Update":
        logger.info("CodeInterpreter Update — no-op, returning existing ID: %s", physical_id)
        return _cfn_response(physical_id, {"CodeInterpreterId": physical_id})

    if request_type == "Delete":
        try:
            client.delete_code_interpreter(codeInterpreterId=physical_id)
            logger.info("Deleted Code Interpreter: %s", physical_id)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                logger.info("CodeInterpreter %s already deleted — skipping", physical_id)
            else:
                raise
        return _cfn_response(physical_id, {})

    raise ValueError(f"Unknown RequestType: {request_type!r}")


# ── Gateway ───────────────────────────────────────────────────────────────────

def _handle_gateway(request_type: str, physical_id: str, props: dict) -> dict:
    client = get_client()
    name       = props["Name"]
    role_arn   = props["RoleArn"]
    nasa_arn   = props["NasaLambdaArn"]
    noaa_arn   = props["NoaaLambdaArn"]

    if request_type == "Create":
        existing = [
            g for g in client.list_gateways().get("gatewaySummaries", [])
            if g["name"] == name
        ]
        if existing:
            gw_id = existing[0]["gatewayId"]
            logger.info("Gateway already exists — reusing: %s", gw_id)
        else:
            # IAM roles are eventually consistent; retry with backoff if the
            # Gateway rejects the role ARN with an InvalidParameter error.
            gw_id = _create_gateway_with_retry(client, name, role_arn)

        _wait_active(
            lambda gid: client.get_gateway(gatewayId=gid)["status"],
            gw_id,
            "Gateway",
        )

        _reconcile_gateway_targets(client, gw_id, nasa_arn, noaa_arn)
        return _cfn_response(gw_id, {"GatewayId": gw_id})

    if request_type == "Update":
        # On Update the Gateway itself is unchanged; reconcile targets only
        # in case Lambda ARNs were rotated.
        logger.info("Gateway Update — reconciling targets for: %s", physical_id)
        _reconcile_gateway_targets(client, physical_id, nasa_arn, noaa_arn)
        return _cfn_response(physical_id, {"GatewayId": physical_id})

    if request_type == "Delete":
        try:
            _delete_gateway_targets(client, physical_id)
            client.delete_gateway(gatewayId=physical_id)
            logger.info("Deleted Gateway: %s", physical_id)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                logger.info("Gateway %s already deleted — skipping", physical_id)
            else:
                raise
        return _cfn_response(physical_id, {})

    raise ValueError(f"Unknown RequestType: {request_type!r}")


def _create_gateway_with_retry(client, name: str, role_arn: str, max_attempts: int = 5) -> str:
    """
    Create the Gateway, retrying on InvalidParameterException.

    IAM is eventually consistent: the Gateway service may reject the role ARN
    for up to ~15 seconds after the IAM role is created.  This replaces the
    hard-coded time.sleep(15) in tf_agentcore.py with a cleaner retry loop.
    """
    delay = 10
    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.create_gateway(
                name=name,
                description="Gateway for climate data APIs (NASA POWER, NOAA NCEI)",
                protocolType="MCP",
                authorizerType="NONE",
                roleArn=role_arn,
                protocolConfiguration={"mcp": {"searchType": "SEMANTIC"}},
                exceptionLevel="DEBUG",
            )
            gw_id = resp["gatewayId"]
            logger.info("Created Gateway: %s (attempt %d)", gw_id, attempt)
            return gw_id
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("InvalidParameterException", "ValidationException") and attempt < max_attempts:
                logger.warning(
                    "Gateway creation attempt %d failed (%s) — IAM may not have propagated yet. "
                    "Retrying in %ds…",
                    attempt, code, delay,
                )
                time.sleep(delay)
                delay = min(delay * 2, 60)
            else:
                raise


def _reconcile_gateway_targets(
    client, gw_id: str, nasa_arn: str, noaa_arn: str
) -> None:
    """
    Ensure both Gateway targets exist.  Existing targets are left untouched
    (idempotent); missing targets are created.
    """
    existing = {
        t["name"]
        for t in client.list_gateway_targets(
            gatewayIdentifier=gw_id
        ).get("gatewayTargetSummaries", [])
    }

    targets = [
        {
            "name": "nasa-power-proxy",
            "lambda_arn": nasa_arn,
            "tool_name": "nasa_power_query",
            "tool_description": "Query NASA POWER API for climate data",
            "required": ["latitude", "longitude", "start", "end"],
            "properties": {
                "latitude":   {"type": "number"},
                "longitude":  {"type": "number"},
                "start":      {"type": "string"},
                "end":        {"type": "string"},
                "parameters": {"type": "string"},
            },
        },
        {
            "name": "noaa-ncei-proxy",
            "lambda_arn": noaa_arn,
            "tool_name": "noaa_ncei_query",
            "tool_description": "Query NOAA NCEI for historical climate observations",
            "required": ["dataset", "startDate", "endDate"],
            "properties": {
                "dataset":   {"type": "string"},
                "stations":  {"type": "string"},
                "startDate": {"type": "string"},
                "endDate":   {"type": "string"},
                "dataTypes": {"type": "string"},
            },
        },
    ]

    for t in targets:
        if t["name"] in existing:
            logger.info("Gateway target already exists — skipping: %s", t["name"])
            continue

        client.create_gateway_target(
            gatewayIdentifier=gw_id,
            name=t["name"],
            targetConfiguration={
                "mcp": {
                    "lambda": {
                        "lambdaArn": t["lambda_arn"],
                        "toolSchema": {
                            "inlinePayload": [{
                                "name": t["tool_name"],
                                "description": t["tool_description"],
                                "inputSchema": {
                                    "type": "object",
                                    "properties": t["properties"],
                                    "required": t["required"],
                                },
                            }]
                        },
                    }
                }
            },
            credentialProviderConfigurations=[
                {"credentialProviderType": "GATEWAY_IAM_ROLE"}
            ],
        )
        logger.info("Created Gateway target: %s", t["name"])


def _delete_gateway_targets(client, gw_id: str) -> None:
    """Delete all targets before deleting the Gateway itself."""
    try:
        targets = client.list_gateway_targets(
            gatewayIdentifier=gw_id
        ).get("gatewayTargetSummaries", [])
    except ClientError:
        return  # Gateway may already be gone

    for t in targets:
        try:
            client.delete_gateway_target(
                gatewayIdentifier=gw_id,
                targetId=t["targetId"],
            )
            logger.info("Deleted Gateway target: %s", t["name"])
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
