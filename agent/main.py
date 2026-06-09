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

from botocore.config import Config as BotocoreConfig

model = BedrockModel(
    model_id=MODEL_ID,
    region_name=REGION,
    boto_client_config=BotocoreConfig(read_timeout=120, connect_timeout=10),
)

tools_list = [search_climate_data, generate_chart]
if _memory_available:
    tools_list.extend([recall_research_context, get_recent_turns])

agent = Agent(
    model=model,
    system_prompt=SYSTEM_PROMPT,
    tools=tools_list,
)


def _sanitize_tool_history(agent_instance):
    """Remove orphaned tool_use messages that lack matching tool_result.

    Bedrock ConverseStream requires every tool_use block to have a
    corresponding tool_result in the next user message. If a prior
    request crashed mid-tool-call, the history is malformed.
    This clears the entire history if orphaned tool calls are detected
    (safest approach — avoids complex message surgery).
    """
    messages = agent_instance.messages
    if not messages:
        return

    # Collect all tool_use IDs and tool_result IDs
    tool_use_ids = set()
    tool_result_ids = set()

    for msg in messages:
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict):
                if "toolUse" in block:
                    tool_use_ids.add(block["toolUse"].get("toolUseId", ""))
                if "toolResult" in block:
                    tool_result_ids.add(block["toolResult"].get("toolUseId", ""))

    # If there are orphaned tool_use calls, clear history
    orphaned = tool_use_ids - tool_result_ids
    if orphaned:
        print(f"  ⚠️  Clearing agent history: {len(orphaned)} orphaned tool call(s) detected")
        agent_instance.messages = []


def handle_request(prompt: str, session_id: str = None, actor_id: str = "default"):
    """Handle a single request from the UI or AgentCore Runtime."""
    import glob as _glob

    session_id = session_id or str(uuid.uuid4())

    if _memory_available and os.environ.get("CLIMATE_RAG_MEMORY_ID"):
        try:
            save_turn(actor_id, session_id, "user", prompt)
        except Exception as _mem_err:
            print(f"  Warning: Error storing turn: {_mem_err}")

    # Snapshot charts before call
    chart_dir = os.environ.get(
        "CLIMATE_RAG_CHART_DIR",
        os.path.join(os.environ.get("TEMP", "/tmp"), "climate-rag-charts"),  # nosec B108
    )
    os.makedirs(chart_dir, exist_ok=True)
    before = set(_glob.glob(os.path.join(chart_dir, "*.png")))

    # Prevent context window overflow:
    # Bedrock Claude Sonnet has a 200K token context window, but tool calls
    # and RAG results can fill it quickly. Trim conversation history to
    # keep only the last N messages (preserving system prompt).
    MAX_HISTORY_MESSAGES = 20  # ~20 turns = 10 user/assistant pairs
    if hasattr(agent, "messages") and len(agent.messages) > MAX_HISTORY_MESSAGES:
        # Keep the most recent messages, discard oldest
        agent.messages = agent.messages[-MAX_HISTORY_MESSAGES:]

    # Sanitize history: remove orphaned tool_use messages that lack a
    # matching tool_result. Bedrock rejects conversations with unpaired
    # tool calls (happens when a prior request crashed mid-tool-call).
    if hasattr(agent, "messages") and agent.messages:
        _sanitize_tool_history(agent)

    # Call the agent with context overflow recovery
    try:
        response = agent(prompt)
    except Exception as e:
        error_str = str(e).lower()
        if "too many tokens" in error_str or "context" in error_str or "overflow" in error_str or "input is too long" in error_str:
            # Context overflow — clear history and retry with just this prompt
            print("  ⚠️  Context overflow detected — trimming history and retrying...")
            agent.messages = []
            try:
                response = agent(prompt)
            except Exception:
                return {
                    "response": (
                        "I apologize, but the conversation has grown too large for me to process. "
                        "I've cleared my context. Please re-ask your question."
                    ),
                    "session_id": session_id,
                    "charts": [],
                    "tools_called": [],
                    "guardrail_action": "CONTEXT_OVERFLOW",
                }
        else:
            # Non-overflow error — re-raise
            raise

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
        try:
            save_turn(actor_id, session_id, "assistant", result)
        except Exception as _mem_err:
            print(f"  Warning: Error storing turn: {_mem_err}")

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


def handle_request_streaming(prompt: str, session_id: str = None, actor_id: str = "default"):
    """Stream agent response token-by-token via a generator.

    Yields text chunks as they arrive from Bedrock ConverseStream.
    After the generator is exhausted, call get_streaming_metadata() for
    charts, tools_called, etc.

    Args:
        prompt: User query.
        session_id: Session identifier for memory.
        actor_id: Actor identifier for memory.

    Yields:
        str: Text chunks as they stream from the model.
    """
    import asyncio
    import glob as _glob

    session_id = session_id or str(uuid.uuid4())

    if _memory_available and os.environ.get("CLIMATE_RAG_MEMORY_ID"):
        try:
            save_turn(actor_id, session_id, "user", prompt)
        except Exception as _mem_err:
            print(f"  Warning: Error storing turn: {_mem_err}")

    # Snapshot charts before call
    chart_dir = os.environ.get(
        "CLIMATE_RAG_CHART_DIR",
        os.path.join(os.environ.get("TEMP", "/tmp"), "climate-rag-charts"),  # nosec B108
    )
    os.makedirs(chart_dir, exist_ok=True)
    before = set(_glob.glob(os.path.join(chart_dir, "*.png")))

    # Sanitize history
    MAX_HISTORY_MESSAGES = 20
    if hasattr(agent, "messages") and len(agent.messages) > MAX_HISTORY_MESSAGES:
        agent.messages = agent.messages[-MAX_HISTORY_MESSAGES:]
    if hasattr(agent, "messages") and agent.messages:
        _sanitize_tool_history(agent)

    # Stream tokens from agent via thread + queue (async -> sync bridge)
    full_text = []
    tools_called = []

    import queue
    import threading

    text_queue = queue.Queue()
    done_event = threading.Event()
    error_holder = [None]

    def _stream_in_thread():
        async def _inner():
            try:
                async for event in agent.stream_async(prompt):
                    if isinstance(event, dict) and "data" in event:
                        chunk = event["data"]
                        if chunk:
                            full_text.append(chunk)
                            text_queue.put(chunk)
            except Exception as e:
                error_holder[0] = e
            finally:
                done_event.set()

        asyncio.run(_inner())

    thread = threading.Thread(target=_stream_in_thread, daemon=True)
    thread.start()

    # Yield chunks as they arrive
    while not done_event.is_set() or not text_queue.empty():
        try:
            chunk = text_queue.get(timeout=0.1)
            yield chunk
        except queue.Empty:
            continue

    # Drain any remaining items
    while not text_queue.empty():
        yield text_queue.get_nowait()

    thread.join(timeout=5)

    if error_holder[0]:
        raise error_holder[0]  # type: ignore[misc]

    # Post-stream: collect metadata
    result_text = "".join(full_text)

    # Detect new charts
    after = set(_glob.glob(os.path.join(chart_dir, "*.png")))
    new_charts = sorted(after - before)

    # Extract tool names from agent messages
    try:
        if hasattr(agent, "messages") and agent.messages:
            last_msg = agent.messages[-1]
            for block in last_msg.get("content", []):
                if isinstance(block, dict) and "toolUse" in block:
                    tools_called.append(block["toolUse"].get("name", ""))
    except Exception:
        pass

    # Save assistant turn to memory
    if _memory_available and os.environ.get("CLIMATE_RAG_MEMORY_ID"):
        try:
            save_turn(actor_id, session_id, "assistant", result_text)
        except Exception as _mem_err:
            print(f"  Warning: Error storing turn: {_mem_err}")

    # Store metadata for retrieval after streaming completes
    handle_request_streaming._last_metadata = {
        "response": result_text,
        "session_id": session_id,
        "charts": new_charts,
        "tools_called": tools_called,
    }


# Initialize metadata storage
handle_request_streaming._last_metadata = {}


if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]) or "What is the global temperature trend?"
    result = handle_request(query)
    print(result["response"])
