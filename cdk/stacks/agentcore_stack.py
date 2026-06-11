"""
ClimateRAG — AgentCoreStack

Provisions the three AgentCore resources that have no native CloudFormation
or CDK support (as of CDK v2.170 / April 2026):

  1. AgentCore Memory            — multi-session researcher context store
  2. AgentCore Code Interpreter  — sandboxed Python for chart generation
  3. AgentCore Gateway           — MCP gateway exposing NASA/NOAA Lambdas as tools

Async polling pattern (on_event + is_complete)
───────────────────────────────────────────────
The previous approach blocked inside a single Lambda for up to 12 minutes
waiting for resources to reach ACTIVE, racing against the 14-min Lambda
hard timeout. Code Interpreter consistently takes 10+ minutes, causing
intermittent failures.

The CDK Provider framework natively supports async polling via two handlers:
  - on_event_handler  : called once to CREATE/DELETE the resource. Returns
                        immediately after the API call — does NOT poll.
  - is_complete_handler: called every queryInterval until it returns
                        {"IsComplete": True}. Each invocation polls once
                        and returns in < 1 second.

This means the Lambda timeout only needs to cover a single API call (~5s),
not the full activation wait. The Provider framework manages the retry loop
externally using a Step Functions state machine under the hood.

Timing budget:
  queryInterval : 30 s   — how often is_complete is invoked
  totalTimeout  : 25 min — overall budget before CFN marks the resource FAILED
  Code Interpreter typically reaches ACTIVE in 8-12 min in practice.

Resources provisioned:
  - aws_iam.Role          (AgentCore custom resource Lambda role)
  - aws_lambda.Function   (on_event handler)
  - aws_lambda.Function   (is_complete handler — same code, different entry point)
  - custom_resources.Provider
  - cdk.CustomResource × 3  (Memory / CodeInterpreter / Gateway)

Outputs:
  - MemoryId, CodeInterpreterId, GatewayId  (SSM Parameters + CfnOutputs)
"""

import os
from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    CustomResource,
    RemovalPolicy,
    custom_resources,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_ssm as ssm,
)
from constructs import Construct

# Path to the handler directory (contains handler.py with on_event + is_complete)
_HANDLER_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "custom_resources", "agentcore_handler")
)


class AgentCoreStack(Stack):
    """CDK stack provisioning AgentCore Memory, Code Interpreter, and Gateway."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        nasa_lambda: lambda_.IFunction,
        noaa_lambda: lambda_.IFunction,
        gateway_role: iam.IRole,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── IAM: Custom Resource Lambda execution role ────────────
        # Shared by both on_event and is_complete Lambdas.
        # Needs AgentCore control-plane create/get/list/delete + CloudWatch Logs.
        cr_lambda_role = iam.Role(
            self,
            "AgentCoreCRLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
            description="ClimateRAG AgentCore custom resource provisioner role",
        )
        cr_lambda_role.apply_removal_policy(RemovalPolicy.DESTROY)

        cr_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock-agentcore:*",
                    "bedrock-agentcore-control:*",
                    "iam:PassRole",
                ],
                resources=["*"],
            )
        )

        # ── on_event Lambda ───────────────────────────────────────
        # Called once per CFN Create/Update/Delete.
        # Only makes the API call and returns the resource ID immediately.
        # Short timeout is fine — no polling happens here.
        on_event_lambda = lambda_.Function(
            self,
            "AgentCoreCROnEvent",
            runtime=lambda_.Runtime.PYTHON_3_12,
            # handler.on_event — the create/delete entry point
            handler="handler.on_event",
            code=lambda_.Code.from_asset(_HANDLER_DIR),
            role=cr_lambda_role,
            timeout=Duration.seconds(60),
            memory_size=256,
            description="ClimateRAG — AgentCore CR on_event (create/delete API calls)",
        )
        on_event_lambda.apply_removal_policy(RemovalPolicy.DESTROY)

        # ── is_complete Lambda ────────────────────────────────────
        # Called every queryInterval by the Provider framework.
        # Polls the resource status once and returns IsComplete True/False.
        # Short timeout — each poll is a single API call.
        is_complete_lambda = lambda_.Function(
            self,
            "AgentCoreCRIsComplete",
            runtime=lambda_.Runtime.PYTHON_3_12,
            # handler.is_complete — the polling entry point
            handler="handler.is_complete",
            code=lambda_.Code.from_asset(_HANDLER_DIR),
            role=cr_lambda_role,
            timeout=Duration.seconds(30),
            memory_size=256,
            description="ClimateRAG — AgentCore CR is_complete (status polling)",
        )
        is_complete_lambda.apply_removal_policy(RemovalPolicy.DESTROY)

        # ── CDK Custom Resource Provider ──────────────────────────
        # The Provider framework manages the polling loop externally
        # (Step Functions state machine) — no blocking inside Lambda.
        #
        # queryInterval : how often is_complete is called (30 s)
        # totalTimeout  : overall budget before CFN marks FAILED (40 min)
        #   Code Interpreter can take 15-25 min in some accounts.
        #   40 min gives ample headroom while staying under CFN's 60-min limit.
        provider = custom_resources.Provider(
            self,
            "AgentCoreCRProvider",
            on_event_handler=on_event_lambda,
            is_complete_handler=is_complete_lambda,
            query_interval=Duration.seconds(30),
            total_timeout=Duration.minutes(40),
        )

        # ── Custom Resource 1: Memory ─────────────────────────────
        memory_resource = CustomResource(
            self,
            "AgentCoreMemory",
            service_token=provider.service_token,
            properties={
                "ResourceType":    "Memory",
                "Name":            "ClimateRAGMemory",
                "Description":     "Climate research memory — researcher context and findings",
                # eventExpiryDuration is REQUIRED by the API (integer days).
                # CFN passes all properties as strings; handler casts to int.
                "EventExpiryDays": "30",
            },
        )
        memory_id = memory_resource.get_att_string("MemoryId")

        # ── Custom Resource 2: Code Interpreter ───────────────────
        code_interpreter_resource = CustomResource(
            self,
            "AgentCoreCodeInterpreter",
            service_token=provider.service_token,
            properties={
                "ResourceType": "CodeInterpreter",
                "Name":         "ClimateChartInterpreter",
                "Description":  "Sandboxed Python for climate data chart generation",
            },
        )
        code_interpreter_id = code_interpreter_resource.get_att_string("CodeInterpreterId")

        # ── Custom Resource 3: Gateway ────────────────────────────
        # Explicit dependency ensures Memory and CodeInterpreter are ACTIVE
        # before the Gateway is created (Gateway targets reference their IDs).
        gateway_resource = CustomResource(
            self,
            "AgentCoreGateway",
            service_token=provider.service_token,
            properties={
                "ResourceType":  "Gateway",
                "Name":          "ClimateDataGateway",
                "RoleArn":       gateway_role.role_arn,
                "NasaLambdaArn": nasa_lambda.function_arn,
                "NoaaLambdaArn": noaa_lambda.function_arn,
            },
        )
        gateway_resource.node.add_dependency(memory_resource)
        gateway_resource.node.add_dependency(code_interpreter_resource)
        gateway_id = gateway_resource.get_att_string("GatewayId")

        # ── SSM Parameters ────────────────────────────────────────
        # Store IDs in SSM so the agent reads its own config at runtime
        # without hardcoded .env values.
        ssm.StringParameter(
            self,
            "MemoryIdParam",
            parameter_name="/climate-rag/memory-id",
            string_value=memory_id,
            description="AgentCore Memory ID for ClimateRAG",
        )

        ssm.StringParameter(
            self,
            "CodeInterpreterIdParam",
            parameter_name="/climate-rag/code-interpreter-id",
            string_value=code_interpreter_id,
            description="AgentCore Code Interpreter ID for ClimateRAG",
        )

        ssm.StringParameter(
            self,
            "GatewayIdParam",
            parameter_name="/climate-rag/gateway-id",
            string_value=gateway_id,
            description="AgentCore Gateway ID for ClimateRAG",
        )

        # ── Outputs ───────────────────────────────────────────────
        CfnOutput(
            self,
            "MemoryId",
            value=memory_id,
            description="AgentCore Memory ID",
            export_name="ClimateRag-MemoryId",
        )

        CfnOutput(
            self,
            "CodeInterpreterId",
            value=code_interpreter_id,
            description="AgentCore Code Interpreter ID",
            export_name="ClimateRag-CodeInterpreterId",
        )

        CfnOutput(
            self,
            "GatewayId",
            value=gateway_id,
            description="AgentCore Gateway ID",
            export_name="ClimateRag-GatewayId",
        )

        CfnOutput(
            self,
            "AgentEnvVars",
            value=(
                f"CLIMATE_RAG_MEMORY_ID={memory_id} "
                f"CLIMATE_RAG_CODE_INTERPRETER_ID={code_interpreter_id}"
            ),
            description="Environment variables to set before running the Streamlit UI",
        )
