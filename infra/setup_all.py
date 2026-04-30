"""
ClimateRAG — Full infrastructure setup script.
Creates: S3 bucket, Lambda functions, IAM roles, AgentCore Memory,
         Code Interpreter, and Gateway with targets.

Run from the climate-rag/ directory:
    python infra/setup_all.py

Outputs a .env file with all required environment variables.
"""

import boto3
import json
import os
import sys
import time
import zipfile
import io

REGION = os.environ.get("AWS_REGION", "us-east-1")
PROJECT = "climate-rag"

sts = boto3.client("sts", region_name=REGION)
ACCOUNT_ID = sts.get_caller_identity()["Account"]

s3 = boto3.client("s3", region_name=REGION)
iam = boto3.client("iam", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)
agentcore = boto3.client("bedrock-agentcore-control", region_name=REGION)


def log(msg):
    print(f"  {msg}")


def section(title):
    print(f"\n{'='*55}")
    print(f"  {title}")
    print(f"{'='*55}")


# ── S3 Bucket ────────────────────────────────────────────────────
"""
Sets up the S3 bucket for storing climate data. The bucket is named using the pattern {PROJECT}-index-{ACCOUNT_ID} to ensure uniqueness.
The script attempts to create the bucket and handles the case where the bucket already exists (either owned by the user or another account).
It also applies a public access block to ensure the bucket is not publicly accessible. 
This bucket will be used by the AgentCore Memory for storing and retrieving the climate data context.
"""
def setup_s3():
    section("S3 Bucket")
    bucket = f"{PROJECT}-index-{ACCOUNT_ID}"
    try:
        if REGION == "us-east-1":
            s3.create_bucket(Bucket=bucket)
        else:
            s3.create_bucket(Bucket=bucket,
                CreateBucketConfiguration={"LocationConstraint": REGION})
        log(f"Created bucket: {bucket}")
    except s3.exceptions.BucketAlreadyOwnedByYou:
        log(f"Bucket already exists: {bucket}")
    except Exception as e:
        if "BucketAlreadyExists" in str(e):
            log(f"Bucket already exists: {bucket}")
        else:
            raise

    # Block public access
    s3.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
        }
    )
    log("Public access blocked")
    return bucket


# ── IAM Role for Lambda ──────────────────────────────────────────
"""
Sets up the IAM role for the Lambda functions. The role is named {PROJECT}-lambda-role and 
has a trust policy allowing Lambda service to assume it. 
The AWSLambdaBasicExecutionRole managed policy is attached to allow the Lambda functions to write logs to CloudWatch.
The script checks if the role already exists and handles that case gracefully. 
The ARN of the role is returned for use in Lambda function creation.
"""
def setup_lambda_role():
    section("IAM Role — Lambda")
    role_name = f"{PROJECT}-lambda-role"
    trust = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow",
                        "Principal": {"Service": "lambda.amazonaws.com"},
                        "Action": "sts:AssumeRole"}]
    })
    try:
        resp = iam.create_role(RoleName=role_name, AssumeRolePolicyDocument=trust)
        role_arn = resp["Role"]["Arn"]
        log(f"Created role: {role_name}")
    except iam.exceptions.EntityAlreadyExistsException:
        role_arn = iam.get_role(RoleName=role_name)["Role"]["Arn"]
        log(f"Role already exists: {role_name}")

    iam.attach_role_policy(
        RoleName=role_name,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
    )
    log("Attached AWSLambdaBasicExecutionRole")
    time.sleep(10)  # IAM propagation
    return role_arn


# ── Lambda Functions ─────────────────────────────────────────────

def _zip_file(filepath):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(filepath, "handler.py")
    buf.seek(0)
    return buf.read()

"""
Sets up the Lambda functions for NASA POWER and NOAA NCEI API access.
The function code is zipped and uploaded directly via the AWS SDK.
The script checks if the Lambda functions already exist and updates the code if they do.
The ARNs of the created or updated Lambda functions are returned for use in the Gateway setup.
"""
def setup_lambda(name, handler_path, role_arn, env_vars=None):
    func_name = f"{PROJECT}-{name}"
    code = _zip_file(handler_path)
    kwargs = dict(
        FunctionName=func_name,
        Runtime="python3.12",
        Role=role_arn,
        Handler="handler.handler",
        Code={"ZipFile": code},
        Timeout=30,
        Environment={"Variables": env_vars or {}},
    )
    try:
        resp = lam.create_function(**kwargs)
        arn = resp["FunctionArn"]
        log(f"Created Lambda: {func_name}")
    except lam.exceptions.ResourceConflictException:
        lam.update_function_code(FunctionName=func_name, ZipFile=code)
        arn = lam.get_function(FunctionName=func_name)["Configuration"]["FunctionArn"]
        log(f"Updated Lambda: {func_name}")

    # Wait for active state
    for _ in range(20):
        state = lam.get_function(FunctionName=func_name)["Configuration"]["State"]
        if state == "Active":
            break
        time.sleep(3)
    return arn


def setup_lambdas(role_arn):
    section("Lambda Functions")
    base = os.path.join(os.path.dirname(__file__), "..", "gateway")
    nasa_arn = setup_lambda(
        "nasa-power",
        os.path.join(base, "lambda_nasa_power", "handler.py"),
        role_arn
    )
    noaa_arn = setup_lambda(
        "noaa-ncei",
        os.path.join(base, "lambda_noaa_ncei", "handler.py"),
        role_arn
    )
    return nasa_arn, noaa_arn


# ── IAM Role for Gateway ─────────────────────────────────────────
""""
Sets up the IAM role for the AgentCore Gateway. The role is named {PROJECT}-gateway-role and has a trust policy 
allowing the Bedrock AgentCore service to assume it.
The script checks if the role already exists and handles that case gracefully.
The role is granted permission to invoke the Lambda functions created for NASA POWER and NOAA NCEI API access. 
The ARN of the role is returned for use in the Gateway creation.
"""
def setup_gateway_role(nasa_arn, noaa_arn):
    section("IAM Role — Gateway")
    role_name = f"{PROJECT}-gateway-role"
    trust = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow",
                        "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                        "Action": "sts:AssumeRole"}]
    })
    try:
        resp = iam.create_role(RoleName=role_name, AssumeRolePolicyDocument=trust)
        role_arn = resp["Role"]["Arn"]
        log(f"Created role: {role_name}")
    except iam.exceptions.EntityAlreadyExistsException:
        role_arn = iam.get_role(RoleName=role_name)["Role"]["Arn"]
        log(f"Role already exists: {role_name}")

    policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "lambda:InvokeFunction",
                        "Resource": [nasa_arn, noaa_arn]}]
    })
    iam.put_role_policy(RoleName=role_name, PolicyName="invoke-lambda", PolicyDocument=policy)
    log("Attached Lambda invoke policy")
    time.sleep(5)
    return role_arn


# ── AgentCore Memory ─────────────────────────────────────────────
"""
Sets up the AgentCore Memory for storing climate research context and findings. 
The memory is named "ClimateRAGMemory" and uses a semantic memory strategy with a specific namespace configuration.
The script checks if the Memory already exists and returns its ID if found. 
If not, it creates the Memory and waits for it to become ACTIVE before returning the ID. 
The Memory ID is needed for the agent configuration to enable context storage and retrieval.   
"""
def setup_memory():
    section("AgentCore Memory")
    name = "ClimateRAGMemory"

    # Check if already exists
    resp = agentcore.list_memories()
    for m in resp.get("memorySummaries", []):
        if m["name"] == name:
            log(f"Memory already exists: {m['memoryId']}")
            return m["memoryId"]

    resp = agentcore.create_memory(
        name=name,
        description="Climate research memory for researcher context and findings",
        eventExpiryDuration=30,
        memoryStrategies=[{
            "semanticMemoryStrategy": {
                "name": "climateSemanticMemory",
                "namespaceConfiguration": {
                    "namespaceTemplates": ["/strategies/{memoryStrategyId}/actors/{actorId}/"]
                }
            }
        }]
    )
    memory_id = resp["memory"]["memoryId"]
    log(f"Created memory: {memory_id}")

    # Wait for ACTIVE
    log("Waiting for memory to become ACTIVE...")
    for _ in range(40):
        mem_resp = agentcore.get_memory(memoryId=memory_id)
        status = mem_resp.get("status") or mem_resp.get("memory", {}).get("status")
        if status == "ACTIVE":
            break
        log(f"  status: {status}")
        time.sleep(10)
    log("Memory is ACTIVE")
    return memory_id


# ── AgentCore Code Interpreter ───────────────────────────────────

def setup_code_interpreter():
    section("AgentCore Code Interpreter")
    name = "ClimateChartInterpreter"

    # Check if already exists
    resp = agentcore.list_code_interpreters()
    for ci in resp.get("codeInterpreterSummaries", []):
        if ci["name"] == name:
            log(f"Code Interpreter already exists: {ci['codeInterpreterId']}")
            return ci["codeInterpreterId"]

    resp = agentcore.create_code_interpreter(
        name=name,
        description="Sandboxed Python for climate data chart generation",
        networkConfiguration={"networkMode": "PUBLIC"}
    )
    ci_id = resp.get("codeInterpreterId") or resp.get("codeInterpreter", {}).get("codeInterpreterId")
    log(f"Created Code Interpreter: {ci_id}")

    # Wait for ACTIVE
    log("Waiting for Code Interpreter to become ACTIVE...")
    for _ in range(40):
        ci_resp = agentcore.get_code_interpreter(codeInterpreterIdentifier=ci_id)
        status = ci_resp.get("status") or ci_resp.get("codeInterpreter", {}).get("status")
        if status == "ACTIVE":
            break
        log(f"  status: {status}")
        time.sleep(10)
    log("Code Interpreter is ACTIVE")
    return ci_id


# ── AgentCore Gateway ────────────────────────────────────────────

def setup_gateway(gateway_role_arn, nasa_arn, noaa_arn):
    section("AgentCore Gateway")
    name = "ClimateDataGateway"

    # Check if already exists
    resp = agentcore.list_gateways()
    for gw in resp.get("gatewaySummaries", []):
        if gw["name"] == name:
            gw_id = gw["gatewayId"]
            log(f"Gateway already exists: {gw_id}")
            _setup_gateway_targets(gw_id, nasa_arn, noaa_arn)
            return gw_id

    resp = agentcore.create_gateway(
        name=name,
        description="Gateway for climate data APIs (NASA POWER, NOAA NCEI)",
        protocolType="MCP",
        authorizerType="NONE",
        roleArn=gateway_role_arn,
        protocolConfiguration={"mcp": {"searchType": "SEMANTIC"}},
        exceptionLevel="DEBUG",
    )
    gw_id = resp.get("gatewayId") or resp.get("gateway", {}).get("gatewayId")
    log(f"Created Gateway: {gw_id}")

    # Wait for ACTIVE
    log("Waiting for Gateway to become ACTIVE...")
    for _ in range(40):
        gw_resp = agentcore.get_gateway(gatewayIdentifier=gw_id)
        status = gw_resp.get("status") or gw_resp.get("gateway", {}).get("status")
        if status == "ACTIVE":
            break
        log(f"  status: {status}")
        time.sleep(10)
    log("Gateway is ACTIVE")

    _setup_gateway_targets(gw_id, nasa_arn, noaa_arn)
    return gw_id


def _setup_gateway_targets(gw_id, nasa_arn, noaa_arn):
    # Check existing targets
    existing = {
        t["name"]
        for t in agentcore.list_gateway_targets(gatewayIdentifier=gw_id).get("gatewayTargetSummaries", [])
    }

    if "nasa-power-proxy" not in existing:
        agentcore.create_gateway_target(
            gatewayIdentifier=gw_id,
            name="nasa-power-proxy",
            targetConfiguration={"mcp": {"lambda": {
                "lambdaArn": nasa_arn,
                "toolSchema": {"inlinePayload": [{
                    "name": "nasa_power_query",
                    "description": "Query NASA POWER API for climate data",
                    "inputSchema": {"type": "object", "properties": {
                        "latitude": {"type": "number"},
                        "longitude": {"type": "number"},
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                        "parameters": {"type": "string"}
                    }, "required": ["latitude", "longitude", "start", "end"]}
                }]}
            }}},
            credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}]
        )
        log("Created Gateway target: nasa-power-proxy")
    else:
        log("Gateway target already exists: nasa-power-proxy")

    if "noaa-ncei-proxy" not in existing:
        agentcore.create_gateway_target(
            gatewayIdentifier=gw_id,
            name="noaa-ncei-proxy",
            targetConfiguration={"mcp": {"lambda": {
                "lambdaArn": noaa_arn,
                "toolSchema": {"inlinePayload": [{
                    "name": "noaa_ncei_query",
                    "description": "Query NOAA NCEI for historical climate observations",
                    "inputSchema": {"type": "object", "properties": {
                        "dataset": {"type": "string"},
                        "stations": {"type": "string"},
                        "startDate": {"type": "string"},
                        "endDate": {"type": "string"},
                        "dataTypes": {"type": "string"}
                    }, "required": ["dataset", "startDate", "endDate"]}
                }]}
            }}},
            credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}]
        )
        log("Created Gateway target: noaa-ncei-proxy")
    else:
        log("Gateway target already exists: noaa-ncei-proxy")


# ── Write .env file ──────────────────────────────────────────────

def write_env(bucket, memory_id, ci_id):
    section("Writing .env file")
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    content = f"""# ClimateRAG environment variables — generated by setup_all.py
AWS_REGION={REGION}
AWS_DEFAULT_REGION={REGION}
CLIMATE_RAG_BUCKET={bucket}
CLIMATE_RAG_MEMORY_ID={memory_id}
CLIMATE_RAG_CODE_INTERPRETER_ID={ci_id}
"""
    with open(env_path, "w") as f:
        f.write(content)
    log(f"Written to: {os.path.abspath(env_path)}")
    print("\n  Set these in your shell before running Streamlit:")
    print(f"    $env:CLIMATE_RAG_BUCKET = \"{bucket}\"")
    print(f"    $env:CLIMATE_RAG_MEMORY_ID = \"{memory_id}\"")
    print(f"    $env:CLIMATE_RAG_CODE_INTERPRETER_ID = \"{ci_id}\"")
    print(f"    $env:AWS_REGION = \"{REGION}\"")


# ── Main ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\nClimateRAG Infrastructure Setup")
    print(f"Account: {ACCOUNT_ID} | Region: {REGION}")

    bucket = setup_s3()
    lambda_role_arn = setup_lambda_role()
    nasa_arn, noaa_arn = setup_lambdas(lambda_role_arn)
    gateway_role_arn = setup_gateway_role(nasa_arn, noaa_arn)
    memory_id = setup_memory()
    ci_id = setup_code_interpreter()
    setup_gateway(gateway_role_arn, nasa_arn, noaa_arn)
    write_env(bucket, memory_id, ci_id)

    section("Done")
    print(f"  All infrastructure is ready.\n")
