"""Setup AgentCore Gateway with Lambda targets for NASA/NOAA APIs."""

import json
import boto3

REGION = "us-east-1"
GATEWAY_NAME = "ClimateDataGateway"


def create_gateway():
    """Create AgentCore Gateway with semantic search enabled."""
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    print(f"Creating Gateway: {GATEWAY_NAME}...")
    resp = client.create_gateway(
        name=GATEWAY_NAME,
        description="Gateway for climate data APIs (NASA POWER, NOAA NCEI)",
        protocolConfiguration={"mcp": {}},
    )

    gateway_id = resp["gatewayId"]
    print(f"Gateway created. ID: {gateway_id}")
    return gateway_id


def add_lambda_target(gateway_id, target_name, lambda_arn, description):
    """Add a Lambda function as a Gateway target."""
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    print(f"Adding target: {target_name}...")
    resp = client.create_gateway_target(
        gatewayIdentifier=gateway_id,
        name=target_name,
        description=description,
        targetConfiguration={
            "lambdaTarget": {"lambdaArn": lambda_arn}
        },
    )
    print(f"  Target ID: {resp['targetId']}")


def main():
    gateway_id = create_gateway()

    print("\nTo add Lambda targets, deploy the Lambda functions first, then run:")
    print(f"  python setup_gateway.py add-target {gateway_id} <lambda-arn>")
    print(f"\nGateway ID: {gateway_id}")


if __name__ == "__main__":
    main()
