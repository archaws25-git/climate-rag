"""
ClimateRAG — AgentCoreStack

Provisions the three AgentCore resources that have no native CloudFormation
or CDK support (as of CDK v2.170 / April 2026):

  1. AgentCore Memory        — multi-session researcher context store
  2. AgentCore Code Interpreter — sandboxed Python for chart generation
  3. AgentCore Gateway       — MCP gateway exposing NASA/NOAA Lambdas as tools

Each resource is backed by a Lambda-backed Custom Resource.  A single
shared Lambda function (agentcore_handler/handler.py) handles all three
resource types via a ResourceType discriminator in ResourceProperties.

Why Lambda-backed Custom Resource over AwsCustomResource
─────────────────────────────────────────────────────────
AwsCustomResource fires an SDK call once and returns immediately.
AgentCore Memory and Code Interpreter both require a polling loop
(~3 min to reach ACTIVE status).  The Lambda-backed pattern allows
_wait_active() to run inside the Lambda timeout (15 min max), which is
the only correct way to handle this without a separate Step Function.

Custom Resource timeout budget
────────────────────────────────
  Memory            : up to  5 min to ACTIVE
  Code Interpreter  : up to  5 min to ACTIVE
  Gateway           : up to  2 min to ACTIVE  (+ IAM retry ~30s)
  Total (sequential): ~12 min worst case
  Lambda timeout set: 14 min (leaves 1 min buffer before CFN timeout at 60 min)

Resources provisioned:
  - aws_iam.Role                  (AgentCore custom resource Lambda role)
  - aws_lambda.Function           (shared AgentCore provisioner)
  - custom_resources.Provider     (wraps Lambda as a CFN CR provider)
  - cdk.CustomResource × 3        (Memory / CodeInterpreter / Gateway)

Outputs:
  - MemoryId, CodeInterpreterId, GatewayId   (SSM Parameters + CfnOutputs)
    Written to SSM so the agent can read its own config at runtime without
    hardcoding IDs in .env files.
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

_HANDLER_DIR = os.path.join(
    os.path.dirname(__file__), "..", "custom_resources", "agentcore_handler"
)


class AgentCoreStack(Stack):
    """AgentCore Memory, Code Interpreter, and Gateway via Custom Resources."""

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
        # Needs permission to call the AgentCore control-plane APIs for
        # create / describe / list / delete on all three resource types,
        # plus basic Lambda execution (CloudWatch Logs).
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


        # Least-privilege AgentCore control-plane permissions.
        # bedrock-agentcore is the service prefix for the
        # AgentCore management API (create/get/list/delete).
        cr_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock-agentcore:*",
                    "iam:PassRole",
                ],
                resources=["*"],
            )
        )

        # ── Shared Custom Resource Lambda ─────────────────────────
        # One function handles Memory, CodeInterpreter, and Gateway.
        # Timeout is 14 min to accommodate the ~5 min ACTIVE wait for
        # Memory and Code Interpreter (CFN waits up to 60 min by default).
        cr_lambda = lambda_.Function(
            self,
            "AgentCoreCRLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(os.path.abspath(_HANDLER_DIR)),
            role=cr_lambda_role,
            timeout=Duration.minutes(14),
            memory_size=256,
            description=(
                "ClimateRAG — AgentCore custom resource provisioner "
                "(Memory / CodeInterpreter / Gateway)"
            ),
        )
        cr_lambda.apply_removal_policy(RemovalPolicy.DESTROY)


        # ── CDK Custom Resource Provider ─────────────────────────
        # Provider wraps the Lambda as a CFN custom resource service token.
        # Completion is handled inside the Lambda itself via _wait_active().
        provider = custom_resources.Provider(
            self,
            "AgentCoreCRProvider",
            on_event_handler=cr_lambda,
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
        # Depends on Memory and CodeInterpreter being ACTIVE first
        # (belt-and-suspenders — CFN serialises these already since they
        # share the same Provider).
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
        # via boto3 SSM rather than hardcoded .env values.  This removes
        # the need for the setup_all.py .env file generation step.
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
