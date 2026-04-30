import re
import time
import logging
import boto3
from botocore.exceptions import ClientError

# Configure logging to capture lifecycle events for debugging in CloudWatch
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# REGEX VALIDATION
# This pattern matches the AWS requirement: [a-zA-Z][a-zA-Z0-9-_]{0,99}-[a-zA-Z0-9]{10}
# It prevents ValidationException during Delete/Update if a dummy physical ID exists.
ID_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9-_]{0,99}-[a-zA-Z0-9]{10}$")

def handler(event, context):
    """
    Main entry point for the CloudFormation Custom Resource.
    Dispatches events based on ResourceType to ensure modular management 
    of Memory, Code Interpreter, and Gateway resources.
    """
    resource_type = event.get("ResourceType")
    request_type = event.get("RequestType")
    physical_id = event.get("PhysicalResourceId")
    props = event.get("ResourceProperties")
    
    # Standard Bedrock AgentCore client
    client = boto3.client("bedrock-agentcore")

    # Resource Dispatcher: Maps CFN ResourceTypes to their respective handler functions.
    # This preserves the original functionality for all three resource types.
    dispatch = {
        "Custom::AgentCoreMemory": _handle_memory,
        "Custom::AgentCoreCodeInterpreter": _handle_code_interpreter,
        "Custom::AgentCoreGateway": _handle_gateway,
    }

    if resource_type in dispatch:
        return dispatch[resource_type](client, request_type, physical_id, props)
    
    logger.error(f"Unknown ResourceType requested: {resource_type}")
    return {"PhysicalResourceId": physical_id or "na"}

def _wait_active(client, resource_id, resource_type):
    """
    Polls the resource status until it reaches the 'ACTIVE' state.
    This is critical because AgentCore resources are provisioned asynchronously
    and subsequent stack resources (like the Agent) depend on these being ready.
    """
    max_attempts = 20
    delay = 15 # Total wait time approx 5 minutes
    
    for attempt in range(max_attempts):
        try:
            # Determine which 'get' operation to use based on resource category
            if resource_type == "memory":
                response = client.get_memory(memoryId=resource_id)
            else:
                response = client.get_code_interpreter(codeInterpreterId=resource_id)
            
            status = response.get("status")
            logger.info(f"Polling {resource_type} {resource_id}: Current status is {status}")
            
            if status == "ACTIVE":
                return True
            if status in ["FAILED", "DELETING"]:
                raise Exception(f"{resource_type} {resource_id} reached terminal state: {status}")
        except ClientError as e:
            logger.error(f"Error checking status for {resource_id}: {e}")
            raise e
        time.sleep(delay)
    
    raise Exception(f"Timeout: {resource_type} {resource_id} did not become ACTIVE within 5 minutes.")

# ── MEMORY HANDLER ──────────────────────────────────────────────────
def _handle_memory(client, request_type, physical_id, props):
    """Handles the lifecycle of the AgentCore Memory resource."""
    if request_type == "Create":
        logger.info("Creating AgentCore Memory...")
        res = client.create_memory(name=props["Name"])
        memory_id = res["memoryId"]
        
        # VALIDATION: Ensure the ID from the API is used and verified before waiting
        if not ID_PATTERN.match(memory_id):
            raise ValueError(f"Service returned an invalid memoryId format: {memory_id}")
            
        _wait_active(client, memory_id, "memory")
        return {"PhysicalResourceId": memory_id}

    if request_type == "Delete":
        # SAFETY CHECK: Only attempt API call if the physical_id is a valid AWS ID.
        # This prevents the 'pending' or dummy ID from causing a ValidationException.
        if physical_id and ID_PATTERN.match(physical_id):
            try:
                logger.info(f"Deleting Memory: {physical_id}")
                client.delete_memory(memoryId=physical_id)
            except ClientError as e:
                # Idempotency: If the resource is already gone, treat as success.
                if e.response["Error"]["Code"] != "ResourceNotFoundException":
                    raise
        else:
            logger.warning(f"Invalid PhysicalResourceId for deletion: {physical_id}. Skipping API call.")
            
        return {"PhysicalResourceId": physical_id}
    
    return {"PhysicalResourceId": physical_id}

# ── CODE INTERPRETER HANDLER ────────────────────────────────────────
def _handle_code_interpreter(client, request_type, physical_id, props):
    """Handles the lifecycle of the Code Interpreter resource."""
    if request_type == "Create":
        logger.info("Creating Code Interpreter...")
        res = client.create_code_interpreter(name=props["Name"])
        ci_id = res["codeInterpreterId"]
        
        # Ensure only a valid ID is passed back to CloudFormation
        if not ID_PATTERN.match(ci_id):
            raise ValueError(f"Invalid codeInterpreterId format: {ci_id}")
            
        _wait_active(client, ci_id, "code_interpreter")
        return {"PhysicalResourceId": ci_id}

    if request_type == "Delete":
        if physical_id and ID_PATTERN.match(physical_id):
            try:
                client.delete_code_interpreter(codeInterpreterId=physical_id)
            except ClientError as e:
                if e.response["Error"]["Code"] != "ResourceNotFoundException":
                    raise
        return {"PhysicalResourceId": physical_id}
    
    return {"PhysicalResourceId": physical_id}

# ── GATEWAY HANDLER ─────────────────────────────────────────────────
def _handle_gateway(client, request_type, physical_id, props):
    """
    Handles the Gateway resource and its associated Targets.
    Unlike Memory/CI, Gateways often require reconciliation during Updates.
    """
    if request_type == "Create":
        logger.info("Creating Gateway...")
        res = client.create_gateway(
            name=props["Name"],
            roleArn=props["RoleArn"]
        )
        gw_id = res["gatewayId"]
        # Provision nested targets immediately after gateway creation
        _create_gateway_targets(client, gw_id, props.get("Targets", []))
        return {"PhysicalResourceId": gw_id}

    if request_type == "Update":
        # RECONCILE: Existing functionality for updates ensures targets are refreshed.
        logger.info(f"Updating targets for Gateway: {physical_id}")
        _delete_gateway_targets(client, physical_id)
        _create_gateway_targets(client, physical_id, props.get("Targets", []))
        return {"PhysicalResourceId": physical_id}

    if request_type == "Delete":
        if physical_id and ID_PATTERN.match(physical_id):
            try:
                # Cleanup child targets before deleting parent Gateway
                _delete_gateway_targets(client, physical_id)
                client.delete_gateway(gatewayId=physical_id)
            except ClientError as e:
                if e.response["Error"]["Code"] != "ResourceNotFoundException":
                    raise
        return {"PhysicalResourceId": physical_id}

    return {"PhysicalResourceId": physical_id}

def _create_gateway_targets(client, gw_id, targets):
    """Iterates through target definitions and maps them as Lambda tools in the Gateway."""
    for t in targets:
        logger.info(f"Adding target {t['name']} to Gateway {gw_id}")
        client.create_gateway_target(
            gatewayIdentifier=gw_id,
            name=t["name"],
            targetType="LAMBDA",
            targetResource={
                "lambdaResource": {
                    "lambda_arn": t["lambda_arn"],
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
            },
            credentialProviderConfigurations=[
                {"credentialProviderType": "GATEWAY_IAM_ROLE"}
            ],
        )

def _delete_gateway_targets(client, gw_id):
    """Identifies and removes all targets associated with a specific Gateway."""
    try:
        targets = client.list_gateway_targets(gatewayIdentifier=gw_id).get("gatewayTargetSummaries", [])
        for t in targets:
            client.delete_gateway_target(gatewayIdentifier=gw_id, targetId=t["targetId"])
    except ClientError:
        # Ignore errors if the gateway itself is already gone
        pass