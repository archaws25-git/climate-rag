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
_reconstruction_available = False
try:
    from tools.history_reconstruction import reconstruct_history
    from tools.memory_tool import get_recent_turns, recall_research_context, save_turn

    _memory_available = True
    _reconstruction_available = True
except ImportError:
    pass

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("CLIMATE_RAG_MODEL", "us.anthropic.claude-sonnet-4-6")

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system_prompt.txt").read_text()

from botocore.config import Config as BotocoreConfig  # noqa: E402

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
    corresponding tool_result in a subsequent user message.

    Strategy:
    1. Find all tool_use IDs and tool_result IDs across the full history.
    2. If any orphans exist, trim messages from the end until the history
       is clean (preserves the oldest valid multi-turn exchanges).
    3. If trimming can't fix it, clear everything.
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

    orphaned = tool_use_ids - tool_result_ids
    if not orphaned:
        return

    # Trim from the end: remove messages until no orphans remain
    while messages:
        # Re-check orphans
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

        if not (tool_use_ids - tool_result_ids):
            break  # History is now clean
        messages.pop()  # Remove last message

    # If we emptied everything or still have orphans, just clear
    if not messages or (tool_use_ids - tool_result_ids):
        agent_instance.messages = []
    else:
        agent_instance.messages = messages

    print(f"  ⚠️  Sanitized agent history: trimmed to {len(agent_instance.messages)} messages")


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
    After the generator is exhausted, metadata (charts, tools, latency)
    is available via handle_request_streaming._last_metadata.

    Args:
        prompt: User query.
        session_id: Session identifier for memory.
        actor_id: Actor identifier for memory.

    Yields:
        str: Text chunks as they stream from the model.
    """
    import asyncio
    import glob as _glob
    import time as _time

    from tracing import get_request_trace, start_request_trace, timed_span

    session_id = session_id or str(uuid.uuid4())
    start_request_trace(session_id)
    _request_start = _time.perf_counter()

    # ── Stage: Memory Save (user turn) ────────────────────────────
    if _memory_available and os.environ.get("CLIMATE_RAG_MEMORY_ID"):
        with timed_span("climate_rag.memory.save_user_turn"):
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

    # ── Stage: History Management ─────────────────────────────────
    MAX_HISTORY_MESSAGES = 20
    if hasattr(agent, "messages") and len(agent.messages) > MAX_HISTORY_MESSAGES:
        agent.messages = agent.messages[-MAX_HISTORY_MESSAGES:]

    # Reconstruct history from Memory if available and in-process history is empty/corrupt
    # Skip on first turn (no prior messages in Streamlit session) to save latency
    if _reconstruction_available and hasattr(agent, "messages"):
        if not agent.messages and os.environ.get("_CLIMATE_RAG_HAS_PRIOR_TURN"):
            with timed_span("climate_rag.history.reconstruct"):
                reconstructed = reconstruct_history(actor_id, session_id)
                if reconstructed:
                    agent.messages = reconstructed
                    print(f"  ℹ️  Reconstructed {len(reconstructed)} messages from Memory")

    # Mark that we've had at least one turn (for next request)
    os.environ["_CLIMATE_RAG_HAS_PRIOR_TURN"] = "1"

    # Sanitize: remove orphaned tool_use messages
    if hasattr(agent, "messages") and agent.messages:
        with timed_span("climate_rag.history.sanitize"):
            _sanitize_tool_history(agent)

    # ── Stage: Agent Streaming ────────────────────────────────────
    full_text = []
    tools_called = []
    _stream_start = _time.perf_counter()

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
                # If orphaned tool_use error, clear history and retry once
                if "Expected toolResult" in str(e) or "toolResult blocks" in str(e):
                    print("  ⚠️  Orphaned tool_use detected — reconstructing from Memory...")
                    agent.messages = []
                    # Try to reconstruct clean history from Memory
                    if _reconstruction_available:
                        reconstructed = reconstruct_history(actor_id, session_id)
                        agent.messages = reconstructed
                    full_text.clear()
                    try:
                        async for event in agent.stream_async(prompt):
                            if isinstance(event, dict) and "data" in event:
                                chunk = event["data"]
                                if chunk:
                                    full_text.append(chunk)
                                    text_queue.put(chunk)
                    except Exception as retry_err:
                        error_holder[0] = retry_err
                else:
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
        with timed_span("climate_rag.memory.save_assistant_turn"):
            try:
                save_turn(actor_id, session_id, "assistant", result_text)
            except Exception as _mem_err:
                print(f"  Warning: Error storing turn: {_mem_err}")

    # Compute total E2E time
    _e2e_ms = round((_time.perf_counter() - _request_start) * 1000, 1)

    # Collect OTel spans for metadata
    trace_data = get_request_trace(session_id)

    # Store metadata for retrieval after streaming completes
    handle_request_streaming._last_metadata = {
        "response": result_text,
        "session_id": session_id,
        "charts": new_charts,
        "tools_called": tools_called,
        "latency": {
            "e2e_ms": _e2e_ms,
            "trace_spans": trace_data,
        },
    }


# Initialize metadata storage
handle_request_streaming._last_metadata = {}


if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]) or "What is the global temperature trend?"
    result = handle_request(query)
    print(result["response"])
