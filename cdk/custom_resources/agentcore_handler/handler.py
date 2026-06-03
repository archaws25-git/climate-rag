"""
AgentCore Custom Resource Handler — async polling pattern.

The CDK Provider framework supports two Lambda entry points:
  - onEvent  : called once by CFN to CREATE / UPDATE / DELETE the resource.
               Must return quickly (< 60s). For Create, just calls the API
               and returns the resource ID. Does NOT poll.
  - isComplete: called repeatedly by the Provider framework (every
               queryInterval seconds, up to totalTimeout) until it returns
               {"IsComplete": True}. Polls the resource status once and
               returns immediately either way.

This split avoids the previous approach of blocking inside a single Lambda
for up to 12 minutes, which was racing against the 14-min Lambda timeout
and causing intermittent failures for Code Interpreter (slowest to activate).

Provider framework timing (set in agentcore_stack.py):
  queryInterval : 30 seconds between isComplete polls
  totalTimeout  : 20 minutes overall budget (well above worst-case ~10 min)
"""

import logging
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Boto3 client ─────────────────────────────────────────────────────
# bedrock-agentcore-control is the control-plane endpoint.
# bedrock-agentcore (no suffix) is the runtime invocation plane — wrong endpoint.
def _client():
    return boto3.client("bedrock-agentcore-control")


# ════════════════════════════════════════════════════════════════════
# ON-EVENT handler — called once per CFN Create / Update / Delete
# Must return quickly. For Create: call the API, return the ID.
# ════════════════════════════════════════════════════════════════════
def on_event(event, context):
    request_type = event["RequestType"]
    props = event.get("ResourceProperties", {})
    resource_type = props.get("ResourceType")
    physical_id = event.get("PhysicalResourceId", "na")

    logger.info("on_event: %s %s physical_id=%s", request_type, resource_type, physical_id)

    dispatch = {
        "Memory":          _on_event_memory,
        "CodeInterpreter": _on_event_code_interpreter,
        "Gateway":         _on_event_gateway,
    }

    fn = dispatch.get(resource_type)
    if fn is None:
        logger.error("Unsupported ResourceType: %s", resource_type)
        # Return success to avoid permanently blocking the stack.
        return {"PhysicalResourceId": physical_id}

    return fn(_client(), request_type, physical_id, props)


# ════════════════════════════════════════════════════════════════════
# IS-COMPLETE handler — called repeatedly until IsComplete=True
# Poll the resource status once and return immediately.
# ════════════════════════════════════════════════════════════════════
def is_complete(event, context):
    request_type = event["RequestType"]
    physical_id = event.get("PhysicalResourceId", "na")
    props = event.get("ResourceProperties", {})
    resource_type = props.get("ResourceType")

    logger.info("is_complete: %s %s physical_id=%s", request_type, resource_type, physical_id)

    # Delete and Update don't need ACTIVE polling — signal done immediately.
    if request_type in ("Delete", "Update"):
        return {"IsComplete": True}

    dispatch = {
        "Memory":          _is_complete_memory,
        "CodeInterpreter": _is_complete_code_interpreter,
        "Gateway":         _is_complete_gateway,
    }

    fn = dispatch.get(resource_type)
    if fn is None:
        logger.error("Unsupported ResourceType in is_complete: %s", resource_type)
        return {"IsComplete": True}

    return fn(_client(), physical_id)


# ════════════════════════════════════════════════════════════════════
# MEMORY
# ════════════════════════════════════════════════════════════════════
def _on_event_memory(client, request_type, physical_id, props):
    if request_type == "Create":
        logger.info("Creating AgentCore Memory: %s", props["Name"])
        res = client.create_memory(
            name=props["Name"],
            # eventExpiryDuration is REQUIRED. CFN sends all props as strings
            # so cast to int explicitly.
            eventExpiryDuration=int(props["EventExpiryDays"]),
        )
        # CreateMemory response: {"memory": {"id": "...", "status": "CREATING", ...}}
        # The ID field is "id", NOT "memoryId".
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

    # Update — nothing to change for now
    return {"PhysicalResourceId": physical_id, "Data": {"MemoryId": physical_id}}


def _is_complete_memory(client, physical_id):
    try:
        res = client.get_memory(memoryId=physical_id)
        # GetMemory response: {"memory": {"status": "ACTIVE"|"CREATING"|"FAILED", ...}}
        status = res["memory"]["status"]
        logger.info("Memory %s status: %s", physical_id, status)
        if status == "ACTIVE":
            return {"IsComplete": True, "Data": {"MemoryId": physical_id}}
        if status == "FAILED":
            raise RuntimeError("Memory %s entered FAILED state" % physical_id)
        # Still CREATING — tell the framework to retry
        return {"IsComplete": False}
    except ClientError as e:
        logger.error("Error polling memory %s: %s", physical_id, e)
        raise


# ════════════════════════════════════════════════════════════════════
# CODE INTERPRETER
# ════════════════════════════════════════════════════════════════════
def _on_event_code_interpreter(client, request_type, physical_id, props):
    if request_type == "Create":
        logger.info("Creating Code Interpreter: %s", props["Name"])
        res = client.create_code_interpreter(
            name=props["Name"],
            # networkConfiguration.networkMode is REQUIRED by the API.
            networkConfiguration={"networkMode": "PUBLIC"},
        )
        # CreateCodeInterpreter response: codeInterpreterId is at the TOP LEVEL,
        # not nested under a "codeInterpreter" key.
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

    # Update — nothing to change for now
    return {"PhysicalResourceId": physical_id, "Data": {"CodeInterpreterId": physical_id}}


def _is_complete_code_interpreter(client, physical_id):
    try:
        res = client.get_code_interpreter(codeInterpreterId=physical_id)
        # GetCodeInterpreter response: status is at the TOP LEVEL (not nested).
        status = res["status"]
        logger.info("Code Interpreter %s status: %s", physical_id, status)
        if status == "ACTIVE":
            return {"IsComplete": True, "Data": {"CodeInterpreterId": physical_id}}
        if status == "FAILED":
            raise RuntimeError("Code Interpreter %s entered FAILED state" % physical_id)
        # Still CREATING — tell the framework to retry
        return {"IsComplete": False}
    except ClientError as e:
        logger.error("Error polling code interpreter %s: %s", physical_id, e)
        raise


# ════════════════════════════════════════════════════════════════════
# GATEWAY
# ════════════════════════════════════════════════════════════════════
def _on_event_gateway(client, request_type, physical_id, props):
    if request_type == "Create":
        logger.info("Creating Gateway: %s", props["Name"])
        res = client.create_gateway(
            name=props["Name"],
            roleArn=props["RoleArn"],
            # protocolType, authorizerType, authorizerConfiguration are all REQUIRED.
            protocolType="MCP",
            authorizerType="NONE",
            authorizerConfiguration={},
            protocolConfiguration={"mcp": {"searchType": "SEMANTIC"}},
            exceptionLevel="DEBUG",
        )
        # CreateGateway response: gatewayId is at the TOP LEVEL.
        gwid = res["gatewayId"]
        logger.info("Gateway created (pending ACTIVE): %s", gwid)
        return {"PhysicalResourceId": gwid, "Data": {"GatewayId": gwid}}

    if request_type == "Update":
        _delete_gateway_targets(client, physical_id)
        _create_gateway_targets(client, physical_id, props.get("Targets", []))
        return {"PhysicalResourceId": physical_id, "Data": {"GatewayId": physical_id}}

    if request_type == "Delete":
        try:
            _delete_gateway_targets(client, physical_id)
            # DeleteGateway requires "gatewayIdentifier", not "gatewayId".
            client.delete_gateway(gatewayIdentifier=physical_id)
            logger.info("Gateway delete requested: %s", physical_id)
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
            logger.info("Gateway already gone: %s", physical_id)
        return {"PhysicalResourceId": physical_id, "Data": {"GatewayId": physical_id}}

    return {"PhysicalResourceId": physical_id, "Data": {"GatewayId": physical_id}}


def _is_complete_gateway(client, physical_id):
    try:
        res = client.get_gateway(gatewayIdentifier=physical_id)
        # GetGateway response: status is at the TOP LEVEL.
        status = res["status"]
        logger.info("Gateway %s status: %s", physical_id, status)
        if status == "ACTIVE":
            # Gateway is ACTIVE — now create the targets
            _create_gateway_targets(client, physical_id, [])
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
def _create_gateway_targets(client, gw_id, targets):
    for t in targets:
        client.create_gateway_target(
            gatewayIdentifier=gw_id,
            name=t["name"],
            targetConfiguration={"mcp": {"lambda": {
                "lambdaArn": t["lambda_arn"],
                "toolSchema": {"inlinePayload": [{
                    "name": t["tool_name"],
                    "description": t["tool_description"],
                    "inputSchema": {
                        "type": "object",
                        "properties": t["properties"],
                        "required": t["required"],
                    },
                }]},
            }}},
            credentialProviderConfigurations=[
                {"credentialProviderType": "GATEWAY_IAM_ROLE"}
            ],
        )


def _delete_gateway_targets(client, gw_id):
    try:
        targets = client.list_gateway_targets(
            gatewayIdentifier=gw_id
        ).get("gatewayTargetSummaries", [])
        for t in targets:
            client.delete_gateway_target(
                gatewayIdentifier=gw_id,
                targetId=t["targetId"],
            )
    except ClientError:
        pass
