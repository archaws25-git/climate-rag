"""
ClimateRAG — ComputeStack

Provisions IAM roles and the two Lambda proxy functions that sit between
AgentCore Gateway and the public NASA / NOAA APIs.

Design notes
────────────
Lambda-as-proxy pattern (retained from original architecture):
  AgentCore Gateway can only target AWS resources — it cannot call an
  arbitrary public HTTPS URL directly.  Each Lambda acts as a thin adapter:
  receives a structured JSON payload from the Gateway, constructs the correct
  API URL, makes an outbound HTTPS call, normalises the response, and returns
  compact JSON back to the agent.

IAM least-privilege:
  - Lambda execution role: AWSLambdaBasicExecutionRole only (CloudWatch Logs).
    No S3, no Bedrock — the Lambdas only make outbound public API calls.
  - Gateway invocation role: lambda:InvokeFunction scoped to the two Lambda
    ARNs only.  The trust policy is scoped to bedrock-agentcore.amazonaws.com.

Resources provisioned:
  - aws_iam.Role  (climate-rag-lambda-role)
  - aws_iam.Role  (climate-rag-gateway-role)
  - aws_lambda.Function  (climate-rag-nasa-power)
  - aws_lambda.Function  (climate-rag-noaa-ncei)

Exports (consumed by AgentCoreStack):
  - nasa_lambda    (aws_lambda.IFunction)
  - noaa_lambda    (aws_lambda.IFunction)
  - gateway_role   (aws_iam.IRole)
"""

import os
from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_iam as iam,
    aws_lambda as lambda_,
)
from constructs import Construct
from aws_cdk.aws_s3 import IBucket

# Resolve the gateway/ directory relative to the CDK project root.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_GATEWAY_DIR = os.path.join(_REPO_ROOT, "gateway")


class ComputeStack(Stack):
    """IAM roles and Lambda proxy functions for NASA/NOAA API access."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        bucket: IBucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── IAM: Lambda Execution Role ────────────────────────────
        # Least-privilege: only CloudWatch Logs writes.
        # Lambdas make outbound public HTTPS calls — no AWS service perms needed.
        lambda_role = iam.Role(
            self,
            "LambdaExecutionRole",
            role_name="climate-rag-lambda-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
            description="ClimateRAG Lambda execution role — CloudWatch Logs only",
        )

        # ── IAM: Gateway Invocation Role ─────────────────────────
        # Scoped to invoking exactly these two Lambda ARNs.
        # Inline policy is attached after the Lambda functions are created
        # so we have their ARNs available.
        self.gateway_role = iam.Role(
            self,
            "GatewayInvocationRole",
            role_name="climate-rag-gateway-role",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            description="ClimateRAG AgentCore Gateway — Lambda invocation role",
        )

        # ── Lambda: NASA POWER Proxy ──────────────────────────────
        self.nasa_lambda = lambda_.Function(
            self,
            "NasaPowerProxy",
            function_name="climate-rag-nasa-power",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(
                os.path.join(_GATEWAY_DIR, "lambda_nasa_power")
            ),
            role=lambda_role,
            timeout=Duration.seconds(30),
            memory_size=128,
            description="Proxy for NASA POWER REST API — temperature/solar/precip data",
            environment={
                "POWERTOOLS_SERVICE_NAME": "climate-rag-nasa-power",
            },
        )

        # ── Lambda: NOAA NCEI Proxy ───────────────────────────────
        self.noaa_lambda = lambda_.Function(
            self,
            "NoaaNceiProxy",
            function_name="climate-rag-noaa-ncei",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(
                os.path.join(_GATEWAY_DIR, "lambda_noaa_ncei")
            ),
            role=lambda_role,
            timeout=Duration.seconds(30),
            memory_size=128,
            description="Proxy for NOAA NCEI Access Data Service API",
            environment={
                "POWERTOOLS_SERVICE_NAME": "climate-rag-noaa-ncei",
            },
        )

        # ── IAM: Attach Gateway → Lambda invoke policy ────────────
        # Now that both Lambda ARNs exist, scope the policy tightly.
        self.gateway_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["lambda:InvokeFunction"],
                resources=[
                    self.nasa_lambda.function_arn,
                    self.noaa_lambda.function_arn,
                ],
            )
        )

        # ── Grant the agent runtime role read access to S3 ────────
        # The RAG tool downloads the FAISS index from this bucket.
        # The actual AgentCore Runtime role ARN is not known at synth time
        # (it is created by AgentCore at deploy time), so we use a
        # resource-based bucket policy scoped to the Bedrock AgentCore
        # service principal instead.
        bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AllowAgentCoreRuntimeReadIndex",
                effect=iam.Effect.ALLOW,
                principals=[
                    iam.ServicePrincipal("bedrock-agentcore.amazonaws.com")
                ],
                actions=["s3:GetObject", "s3:ListBucket"],
                resources=[
                    bucket.bucket_arn,
                    f"{bucket.bucket_arn}/*",
                ],
            )
        )

        # ── Outputs ───────────────────────────────────────────────
        CfnOutput(
            self,
            "NasaLambdaArn",
            value=self.nasa_lambda.function_arn,
            description="NASA POWER proxy Lambda ARN",
            export_name="ClimateRag-NasaLambdaArn",
        )

        CfnOutput(
            self,
            "NoaaLambdaArn",
            value=self.noaa_lambda.function_arn,
            description="NOAA NCEI proxy Lambda ARN",
            export_name="ClimateRag-NoaaLambdaArn",
        )

        CfnOutput(
            self,
            "GatewayRoleArn",
            value=self.gateway_role.role_arn,
            description="AgentCore Gateway IAM role ARN",
            export_name="ClimateRag-GatewayRoleArn",
        )
