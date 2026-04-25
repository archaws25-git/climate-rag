"""Chart tool — saves charts to disk for Streamlit to display."""

import os
import json
import base64
import uuid

import boto3
from strands import tool

REGION = os.environ.get("AWS_REGION", "us-east-1")
CODE_INTERPRETER_ID = os.environ.get("CLIMATE_RAG_CODE_INTERPRETER_ID", "")
CHART_DIR = os.environ.get("CLIMATE_RAG_CHART_DIR", "/tmp/climate-rag-charts")

os.makedirs(CHART_DIR, exist_ok=True)


@tool
def generate_chart(python_code: str, description: str) -> str:
    """Generate a chart by executing Python code in AgentCore Code Interpreter.

    The code MUST:
    1. import matplotlib; matplotlib.use('Agg')
    2. Create the plot
    3. Save to buffer and print base64 with prefix CHART_BASE64:

    Example:
        import matplotlib; matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import base64, io
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot([1,2,3], [4,5,6])
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)
        print('CHART_BASE64:' + base64.b64encode(buf.read()).decode())
        plt.close()

    Args:
        python_code: Python matplotlib code that prints CHART_BASE64:<data>.
        description: What the chart shows.

    Returns:
        Path to saved chart PNG and description.
    """
    if not CODE_INTERPRETER_ID:
        return json.dumps({"status": "error", "error": "Code Interpreter not configured"})

    client = boto3.client("bedrock-agentcore", region_name=REGION)
    session = client.start_code_interpreter_session(
        codeInterpreterIdentifier=CODE_INTERPRETER_ID
    )
    sid = session["sessionId"]

    try:
        resp = client.invoke_code_interpreter(
            codeInterpreterIdentifier=CODE_INTERPRETER_ID,
            sessionId=sid,
            name="executeCode",
            arguments={"code": python_code, "language": "python"},
        )

        stdout = ""
        for event in resp["stream"]:
            if "result" in event:
                stdout = event["result"].get("structuredContent", {}).get("stdout", "")

        b64_image = ""
        for line in stdout.split("\n"):
            if line.startswith("CHART_BASE64:"):
                b64_image = line[len("CHART_BASE64:"):]
                break

        if b64_image:
            chart_id = str(uuid.uuid4())[:8]
            chart_path = os.path.join(CHART_DIR, f"chart_{chart_id}.png")
            with open(chart_path, "wb") as f:
                f.write(base64.b64decode(b64_image))
            return json.dumps({
                "status": "success",
                "chart_path": chart_path,
                "description": description,
            })
        else:
            return json.dumps({"status": "error", "error": f"No chart in output: {stdout[:300]}"})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
    finally:
        try:
            client.stop_code_interpreter_session(
                codeInterpreterIdentifier=CODE_INTERPRETER_ID, sessionId=sid
            )
        except Exception:
            pass
