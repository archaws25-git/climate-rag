"""Chart tool — saves charts to disk for Streamlit to display."""

import base64
import json
import os
import uuid

import boto3
from strands import tool

REGION = os.environ.get("AWS_REGION", "us-east-1")
CODE_INTERPRETER_ID = os.environ.get("CLIMATE_RAG_CODE_INTERPRETER_ID", "")
CHART_DIR = os.environ.get(
    "CLIMATE_RAG_CHART_DIR",
    os.path.join(os.environ.get("TEMP", "/tmp"), "climate-rag-charts"),  # nosec B108
)

os.makedirs(CHART_DIR, exist_ok=True)


@tool
def generate_chart(python_code: str, description: str) -> str:
    """Generate a chart by executing SELF-CONTAINED Python code in a sandboxed interpreter.

    CRITICAL RULES:
    - The sandbox has NO access to any external variables, search results, or DataFrames.
    - ALL data must be hardcoded as Python literals (lists, dicts) INSIDE the code.
    - NEVER use .merge(), .join(), pd.read_json(), or any method that expects external data.
    - NEVER reference variables from outside this code block.
    - If comparing two datasets, define both as inline lists in the code itself.

    The code MUST:
    1. import matplotlib; matplotlib.use('Agg')
    2. Define all data as inline Python literals (lists or dicts)
    3. Create the plot
    4. Save to buffer and print base64 with prefix CHART_BASE64:

    Example for comparing two cities:
        import matplotlib; matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import base64, io

        # ALL DATA MUST BE INLINE — no external variables exist
        decades = ['1950s', '1960s', '1970s', '1980s', '1990s', '2000s', '2010s', '2020s']
        ny_temps = [12.1, 12.3, 12.5, 12.8, 13.0, 13.2, 13.5, 13.8]
        la_temps = [17.2, 17.3, 17.5, 17.8, 18.0, 18.3, 18.5, 18.8]

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(decades, ny_temps, 'b-o', label='New York Central Park')
        ax.plot(decades, la_temps, 'r-o', label='Los Angeles Intl')
        ax.set_xlabel('Decade')
        ax.set_ylabel('Temperature (°C)')
        ax.set_title('Temperature Trends: New York vs Los Angeles')
        ax.legend()
        ax.grid(True, alpha=0.3)

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)
        print('CHART_BASE64:' + base64.b64encode(buf.read()).decode())
        plt.close()

    Args:
        python_code: Self-contained Python code with inline data that prints CHART_BASE64:<data>.
        description: What the chart shows.

    Returns:
        Path to saved chart PNG and description.
    """
    if not CODE_INTERPRETER_ID:
        return json.dumps({"status": "error", "error": "Code Interpreter not configured"})

    # Guard: reject code that tries to use .merge() or .join() on dicts
    # This catches the most common LLM mistake
    dangerous_patterns = [".merge(", "pd.read_json(", "pd.read_csv(", "pd.DataFrame(data)"]
    for pattern in dangerous_patterns:
        if pattern in python_code:
            return json.dumps({
                "status": "error",
                "error": (
                    f"Code contains '{pattern}' which will not work in the sandbox. "
                    "The sandbox has NO external data. "
                    "ALL data values must be hardcoded as Python lists. "
                    "Extract the specific temperature numbers from search results "
                    "and put them directly in the code as: "
                    "ny_temps = [12.1, 12.3, ...] and la_temps = [17.2, 17.3, ...]"
                ),
            })

    client = boto3.client("bedrock-agentcore", region_name=REGION)
    session = client.start_code_interpreter_session(codeInterpreterIdentifier=CODE_INTERPRETER_ID)
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
                b64_image = line[len("CHART_BASE64:") :]
                break

        if b64_image:
            chart_id = str(uuid.uuid4())[:8]
            chart_path = os.path.join(CHART_DIR, f"chart_{chart_id}.png")
            with open(chart_path, "wb") as f:
                f.write(base64.b64decode(b64_image))
            return json.dumps(
                {
                    "status": "success",
                    "chart_path": chart_path,
                    "description": description,
                }
            )

        # Check if stdout contains an error from the sandbox
        error_indicators = [
            "AttributeError", "has no attribute", "NameError",
            "TypeError", "KeyError", "Traceback",
        ]
        if any(indicator in stdout for indicator in error_indicators):
            return json.dumps({
                "status": "error",
                "error": (
                    f"Code execution failed in sandbox: {stdout[:500]}. "
                    "REMINDER: The sandbox has NO external variables or DataFrames. "
                    "You must hardcode ALL data as Python lists. "
                    "Extract the exact temperature values from search results and "
                    "define them inline: decades = ['1950s', ...], temps = [12.1, ...]"
                ),
            })

        return json.dumps({"status": "error", "error": f"No chart in output: {stdout[:300]}"})
    except Exception as e:
        error_msg = str(e)
        if "has no attribute" in error_msg or "merge" in error_msg:
            return json.dumps({
                "status": "error",
                "error": (
                    f"Sandbox error: {error_msg}. "
                    "You cannot use .merge() or access external data in the sandbox. "
                    "Rewrite: define ALL data as inline Python lists, e.g. "
                    "temps = [12.1, 12.3, 12.5, ...] extracted from search results."
                ),
            })
        return json.dumps({"status": "error", "error": error_msg})
    finally:
        try:
            client.stop_code_interpreter_session(codeInterpreterIdentifier=CODE_INTERPRETER_ID, sessionId=sid)
        except Exception:
            pass
