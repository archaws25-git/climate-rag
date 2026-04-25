"""Setup observability — enable CloudWatch Transaction Search for AgentCore."""

import boto3

REGION = "us-east-1"


def main():
    cw = boto3.client("cloudwatch", region_name=REGION)

    print("Observability setup notes:")
    print("=" * 60)
    print("1. Enable CloudWatch Transaction Search in the AWS Console:")
    print("   → CloudWatch → Settings → Transaction Search → Enable")
    print()
    print("2. AgentCore Runtime auto-instruments OTEL traces when deployed")
    print("   via 'agentcore launch'")
    print()
    print("3. View traces at:")
    print("   → CloudWatch → X-Ray traces → Transaction Search")
    print()
    print("4. Agent logs are at:")
    print("   → CloudWatch → Log groups → /aws/bedrock-agentcore/...")
    print()

    # Create a dashboard for key metrics
    dashboard_body = {
        "widgets": [
            {
                "type": "text",
                "x": 0, "y": 0, "width": 24, "height": 2,
                "properties": {
                    "markdown": "# ClimateRAG Observability Dashboard\nMonitor agent performance, tool calls, and errors."
                },
            },
        ],
    }

    print("Creating CloudWatch dashboard: ClimateRAG-Dashboard...")
    cw.put_dashboard(
        DashboardName="ClimateRAG-Dashboard",
        DashboardBody=str(dashboard_body).replace("'", '"'),
    )
    print("Dashboard created.")


if __name__ == "__main__":
    main()
