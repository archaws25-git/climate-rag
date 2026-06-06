"""ClimateRAG — Strands Agent main entry point."""

import json
import os
import uuid
from pathlib import Path

from strands import Agent
from strands.models.bedrock import BedrockModel

from tools.chart_tool import generate_chart
from tools.rag_tool import search_climate_data

# Optional: Memory tools (require bedrock-agentcore SDK)
_memory_available = False
try:
    from tools.memory_tool import get_recent_turns, recall_research_context, save_turn

    _memory_available = True
except ImportError:
    pass

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("CLIMATE_RAG_MODEL", "us.anthropic.claude-sonnet-4-6")

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system_prompt.txt").read_text()

model = BedrockModel(model_id=MODEL_ID, region_name=REGION)

tools_list = [search_climate_data, generate_chart]
if _memory_available:
    tools_list.extend([recall_research_context, get_recent_turns])

agent = Agent(
    model=model,
    system_prompt=SYSTEM_PROMPT,
    tools=tools_list,
)


def handle_request(prompt: str, session_id: str = None, actor_id: str = "default"):
    """Handle a single request from the UI or AgentCore Runtime."""
    import glob as _glob

    session_id = session_id or str(uuid.uuid4())

    if _memory_available and os.environ.get("CLIMATE_RAG_MEMORY_ID"):
        save_turn(actor_id, session_id, "user", prompt)

    # Snapshot charts before call
    chart_dir = os.environ.get(
        "CLIMATE_RAG_CHART_DIR",
        os.path.join(os.environ.get("TEMP", "/tmp"), "climate-rag-charts"),  # nosec B108
    )
    os.makedirs(chart_dir, exist_ok=True)
    before = set(_glob.glob(os.path.join(chart_dir, "*.png")))

    response = agent(prompt)
    result = str(response)

    # Extract tool names that were called during this invocation.
    # Strands stores tool_use blocks in the agent's conversation messages.
    tools_called = []
    try:
        for msg in agent.messages:
            if msg.get("role") == "assistant":
                for block in msg.get("content", []):
                    if isinstance(block, dict) and "toolUse" in block:
                        tools_called.append(block["toolUse"].get("name", ""))
    except Exception:
        pass

    # Detect new charts
    after = set(_glob.glob(os.path.join(chart_dir, "*.png")))
    new_charts = sorted(after - before)

    if _memory_available and os.environ.get("CLIMATE_RAG_MEMORY_ID"):
        save_turn(actor_id, session_id, "assistant", result)

    return {
        "response": result,
        "session_id": session_id,
        "charts": new_charts,
        "tools_called": tools_called,
    }


# AgentCore Runtime entry point
def lambda_handler(event, context=None):
    body = json.loads(event.get("body", "{}")) if isinstance(event.get("body"), str) else event
    prompt = body.get("prompt", "")
    session_id = body.get("session_id")
    actor_id = body.get("actor_id", "default")
    return handle_request(prompt, session_id, actor_id)


if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]) or "What is the global temperature trend?"
    result = handle_request(query)
    print(result["response"])
