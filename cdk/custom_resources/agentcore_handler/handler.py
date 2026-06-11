"""
AgentCore Custom Resource Handler — async polling pattern with idempotency.

Fixes applied:
  1. Idempotent creates — checks if resource with same name exists before
     creating. Handles orphaned resources from previous failed rollbacks.
  2. Gateway targets — created in is_complete after ACTIVE, using props
     from the event (NasaLambdaArn, NoaaLambdaArn).
  3. Retry on AccessDeniedException for Gateway creation (IAM propagation).
  4. totalTimeout raised to 40 min in stack (Code Interpreter can take 25 min).
  5. All exceptions logged clearly so CloudWatch shows what went wrong.
"""

import logging
import time

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _client():
    """bedrock-agentcore-control is the control-plane endpoint."""
    return boto3.client("bedrock-agentcore-control")


# ════════════════════════════════════════════════════════════════════
# ON-EVENT handler
# ════════════════════════════════════════════════════════════════════
def on_event(event, context):
    request_type = event["RequestType"]
    props = event.get("ResourceProperties", {})
    resource_type = props.get("ResourceType")
    physical_id = event.get("PhysicalResourceId", "na")

    logger.info("on_event: %s %s physical_id=%s", request_type, resource_type, physical_id)

    dispatch = {
        "Memory": _on_event_memory,
        "CodeInterpreter": _on_event_code_interpreter,
        "Gateway": _on_event_gateway,
    }

    fn = dispatch.get(resource_type)
    if fn is None:
        logger.error("Unsupported ResourceType: %s", resource_type)
        return {"PhysicalResourceId": physical_id}

    return fn(_client(), request_type, physical_id, props)


# ════════════════════════════════════════════════════════════════════
# IS-COMPLETE handler
# ════════════════════════════════════════════════════════════════════
def is_complete(event, context):
    request_type = event["RequestType"]
    physical_id = event.get("PhysicalResourceId", "na")
    props = event.get("ResourceProperties", {})
    resource_type = props.get("ResourceType")

    logger.info("is_complete: %s %s physical_id=%s", request_type, resource_type, physical_id)

    if request_type in ("Delete", "Update"):
        return {"IsComplete": True}

    dispatch = {
        "Memory": _is_complete_memory,
        "CodeInterpreter": _is_complete_code_interpreter,
        "Gateway": _is_complete_gateway,
    }

    fn = dispatch.get(resource_type)
    if fn is None:
        logger.error("Unsupported ResourceType in is_complete: %s", resource_type)
        return {"IsComplete": True}

    # Pass props through so is_complete_gateway can create targets
    return fn(_client(), physical_id, props)


# ════════════════════════════════════════════════════════════════════
# MEMORY
# ════════════════════════════════════════════════════════════════════
def _on_event_memory(client, request_type, physical_id, props):
    name = props["Name"]

    if request_type == "Create":
        # IDEMPOTENCY: Check if resource with same name already exists
        # (handles orphaned resources from previous failed rollbacks)
        existing = _find_existing_memory(client, name)
        if existing:
            logger.info("Memory already exists (reusing): %s", existing)
            return {"PhysicalResourceId": existing, "Data": {"MemoryId": existing}}

        logger.info("Creating AgentCore Memory: %s", name)
        res = client.create_memory(
            name=name,
            eventExpiryDuration=int(props["EventExpiryDays"]),
        )
        mid = res["memory"]["id"]
        logger.info("Memory created (CREATING): %s", mid)
        return {"PhysicalResourceId": mid, "Data": {"MemoryId": mid}}

    if request_type == "Delete":
        try:
            client.delete_memory(memoryId=physical_id)
            logger.info("Memory delete requested: %s", physical_id)
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
            logger.info("Memory already gone: %s", physical_id)
        return {"PhysicalResourceId": physical_id, "Data": {"MemoryId": physical_id}}

    # Update
    return {"PhysicalResourceId": physical_id, "Data": {"MemoryId": physical_id}}


def _find_existing_memory(client, name):
    """Find an existing memory by name. Returns memoryId or None."""
    try:
        for m in client.list_memories().get("memorySummaries", []):
            if m["name"] == name:
                return m["memoryId"]
    except ClientError:
        pass
    return None


def _is_complete_memory(client, physical_id, props):
    try:
        res = client.get_memory(memoryId=physical_id)
        status = res["memory"]["status"]
        logger.info("Memory %s status: %s", physical_id, status)
        if status == "ACTIVE":
            return {"IsComplete": True, "Data": {"MemoryId": physical_id}}
        if status == "FAILED":
            raise RuntimeError("Memory %s entered FAILED state" % physical_id)
        return {"IsComplete": False}
    except ClientError as e:
        logger.error("Error polling memory %s: %s", physical_id, e)
        raise


# ════════════════════════════════════════════════════════════════════
# CODE INTERPRETER
# ════════════════════════════════════════════════════════════════════
def _on_event_code_interpreter(client, request_type, physical_id, props):
    name = props["Name"]

    if request_type == "Create":
        # IDEMPOTENCY: Check if resource with same name already exists
        existing = _find_existing_code_interpreter(client, name)
        if existing:
            logger.info("Code Interpreter already exists (reusing): %s", existing)
            return {"PhysicalResourceId": existing, "Data": {"CodeInterpreterId": existing}}

        logger.info("Creating Code Interpreter: %s", name)
        res = client.create_code_interpreter(
            name=name,
            networkConfiguration={"networkMode": "PUBLIC"},
        )
        cid = res["codeInterpreterId"]
        logger.info("Code Interpreter created (CREATING): %s", cid)
        return {"PhysicalResourceId": cid, "Data": {"CodeInterpreterId": cid}}

    if request_type == "Delete":
        try:
            client.delete_code_interpreter(codeInterpreterId=physical_id)
            logger.info("Code Interpreter delete requested: %s", physical_id)
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
            logger.info("Code Interpreter already gone: %s", physical_id)
        return {"PhysicalResourceId": physical_id, "Data": {"CodeInterpreterId": physical_id}}

    # Update
    return {"PhysicalResourceId": physical_id, "Data": {"CodeInterpreterId": physical_id}}


def _find_existing_code_interpreter(client, name):
    """Find an existing code interpreter by name. Returns codeInterpreterId or None."""
    try:
        for ci in client.list_code_interpreters().get("codeInterpreterSummaries", []):
            if ci["name"] == name:
                return ci["codeInterpreterId"]
    except ClientError:
        pass
    return None


def _is_complete_code_interpreter(client, physical_id, props):
    try:
        res = client.get_code_interpreter(codeInterpreterId=physical_id)
        status = res["status"]
        logger.info("Code Interpreter %s status: %s", physical_id, status)
        # Code Interpreter returns "READY" (not "ACTIVE") when provisioning completes
        if status in ("ACTIVE", "READY"):
            return {"IsComplete": True, "Data": {"CodeInterpreterId": physical_id}}
        if status == "FAILED":
            raise RuntimeError("Code Interpreter %s entered FAILED state" % physical_id)
        return {"IsComplete": False}
    except ClientError as e:
        logger.error("Error polling code interpreter %s: %s", physical_id, e)
        raise


# ════════════════════════════════════════════════════════════════════
# GATEWAY
# ════════════════════════════════════════════════════════════════════
def _on_event_gateway(client, request_type, physical_id, props):
    name = props["Name"]

    if request_type == "Create":
        # IDEMPOTENCY: Check if gateway with same name already exists
        existing = _find_existing_gateway(client, name)
        if existing:
            logger.info("Gateway already exists (reusing): %s", existing)
            return {"PhysicalResourceId": existing, "Data": {"GatewayId": existing}}

        logger.info("Creating Gateway: %s", name)
        # RETRY for IAM propagation delay — Gateway role from ComputeStack
        # may not be visible to AgentCore for up to 30 seconds.
        gwid = None
        for attempt in range(4):
            try:
                res = client.create_gateway(
                    name=name,
                    roleArn=props["RoleArn"],
                    protocolType="MCP",
                    authorizerType="NONE",
                    # authorizerConfiguration omitted — not required when authorizerType=NONE
                    # Passing {} triggers boto3 tagged union validation error.
                    protocolConfiguration={"mcp": {"searchType": "SEMANTIC"}},
                    exceptionLevel="DEBUG",
                )
                gwid = res["gatewayId"]
                break
            except ClientError as e:
                code = e.response["Error"]["Code"]
                if code in ("AccessDeniedException", "ValidationException") and attempt < 3:
                    logger.warning("Gateway create attempt %d failed (%s), retrying...", attempt + 1, code)
                    time.sleep(10)
                else:
                    raise

        logger.info("Gateway created (pending ACTIVE): %s", gwid)
        return {"PhysicalResourceId": gwid, "Data": {"GatewayId": gwid}}

    if request_type == "Update":
        _delete_gateway_targets(client, physical_id)
        _create_gateway_targets_from_props(client, physical_id, props)
        return {"PhysicalResourceId": physical_id, "Data": {"GatewayId": physical_id}}

    if request_type == "Delete":
        try:
            _delete_gateway_targets(client, physical_id)
            client.delete_gateway(gatewayIdentifier=physical_id)
            logger.info("Gateway delete requested: %s", physical_id)
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
            logger.info("Gateway already gone: %s", physical_id)
        return {"PhysicalResourceId": physical_id, "Data": {"GatewayId": physical_id}}

    return {"PhysicalResourceId": physical_id, "Data": {"GatewayId": physical_id}}


def _find_existing_gateway(client, name):
    """Find an existing gateway by name. Returns gatewayId or None."""
    try:
        for gw in client.list_gateways().get("gatewaySummaries", []):
            if gw["name"] == name:
                return gw["gatewayId"]
    except ClientError:
        pass
    return None


def _is_complete_gateway(client, physical_id, props):
    try:
        res = client.get_gateway(gatewayIdentifier=physical_id)
        status = res["status"]
        logger.info("Gateway %s status: %s", physical_id, status)
        if status == "ACTIVE":
            # FIX: Create targets here using props (NasaLambdaArn, NoaaLambdaArn)
            # which are available from the event's ResourceProperties.
            _create_gateway_targets_from_props(client, physical_id, props)
            return {"IsComplete": True, "Data": {"GatewayId": physical_id}}
        if status == "FAILED":
            raise RuntimeError("Gateway %s entered FAILED state" % physical_id)
        return {"IsComplete": False}
    except ClientError as e:
        logger.error("Error polling gateway %s: %s", physical_id, e)
        raise


# ════════════════════════════════════════════════════════════════════
# GATEWAY TARGET HELPERS
# ════════════════════════════════════════════════════════════════════
def _create_gateway_targets_from_props(client, gw_id, props):
    """Create NASA and NOAA Lambda targets using ResourceProperties.

    This is called from is_complete (after Gateway is ACTIVE) and from
    Update events. The Lambda ARNs come from the CDK stack properties.
    """
    nasa_arn = props.get("NasaLambdaArn")
    noaa_arn = props.get("NoaaLambdaArn")

    if not nasa_arn or not noaa_arn:
        logger.info("No Lambda ARNs in props — skipping target creation")
        return

    # Check which targets already exist (idempotent)
    existing = set()
    try:
        targets = client.list_gateway_targets(gatewayIdentifier=gw_id).get("gatewayTargetSummaries", [])
        existing = {t["name"] for t in targets}
    except ClientError:
        pass

    if "nasa-power-proxy" not in existing:
        client.create_gateway_target(
            gatewayIdentifier=gw_id,
            name="nasa-power-proxy",
            targetConfiguration={
                "mcp": {
                    "lambda": {
                        "lambdaArn": nasa_arn,
                        "toolSchema": {
                            "inlinePayload": [
                                {
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
                                }
                            ]
                        },
                    }
                }
            },
            credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
        )
        logger.info("Created gateway target: nasa-power-proxy")
    else:
        logger.info("Gateway target already exists: nasa-power-proxy")

    if "noaa-ncei-proxy" not in existing:
        client.create_gateway_target(
            gatewayIdentifier=gw_id,
            name="noaa-ncei-proxy",
            targetConfiguration={
                "mcp": {
                    "lambda": {
                        "lambdaArn": noaa_arn,
                        "toolSchema": {
                            "inlinePayload": [
                                {
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
                                }
                            ]
                        },
                    }
                }
            },
            credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
        )
        logger.info("Created gateway target: noaa-ncei-proxy")
    else:
        logger.info("Gateway target already exists: noaa-ncei-proxy")


def _delete_gateway_targets(client, gw_id):
    """Delete all targets from a gateway (best-effort)."""
    try:
        targets = client.list_gateway_targets(gatewayIdentifier=gw_id).get("gatewayTargetSummaries", [])
        for t in targets:
            client.delete_gateway_target(gatewayIdentifier=gw_id, targetId=t["targetId"])
            logger.info("Deleted gateway target: %s", t.get("name", t["targetId"]))
    except ClientError as e:
        logger.warning("Error deleting gateway targets: %s", e)
