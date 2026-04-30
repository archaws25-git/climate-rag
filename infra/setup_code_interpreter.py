"""Setup AgentCore Code Interpreter for chart generation."""

import boto3

REGION = "us-east-1"
NAME = "ClimateChartInterpreter"

"""
This script creates an AgentCore Code Interpreter, 
which is a sandboxed environment for executing code safely. 
In this project, we use it to run Python code that generates charts from climate data. 
The script uses boto3 to call the Bedrock AgentCore Control Plane API to create the Code Interpreter 
and outputs its ID, which is needed for the agent configuration.
"""
def main():
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    print(f"Creating Code Interpreter: {NAME}...")
    resp = client.create_code_interpreter(
        name=NAME,
        description="Sandboxed Python for climate data chart generation",
    )

    ci_id = resp["codeInterpreterIdentifier"]
    print(f"Code Interpreter created. ID: {ci_id}")
    print("Set this environment variable:")
    print(f"  export CLIMATE_RAG_CODE_INTERPRETER_ID={ci_id}")


if __name__ == "__main__":
    main()
