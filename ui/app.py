"""ClimateRAG — Streamlit Chat UI with inline chart rendering.

Self-configuring: reads AgentCore resource IDs from SSM Parameter Store
at startup. Falls back to environment variables if SSM is unavailable.
No manual env var setup needed — just ensure AWS credentials are active.
"""

import os
import sys
import uuid

import boto3
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))

REGION = os.environ.get("AWS_REGION", "us-east-1")

# ── SSM Parameter Names ──────────────────────────────────────────────
SSM_PARAMS = {
    "CLIMATE_RAG_MEMORY_ID": "/climate-rag/memory-id",
    "CLIMATE_RAG_CODE_INTERPRETER_ID": "/climate-rag/code-interpreter-id",
    "CLIMATE_RAG_BUCKET": None,  # Read from env var (set from CloudFormation output)
}


@st.cache_resource
def load_config_from_ssm():
    """Load AgentCore resource IDs from SSM Parameter Store.

    Falls back to environment variables if SSM read fails (e.g., no
    credentials, parameters don't exist yet).
    """
    config = {}
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        for env_var, param_name in SSM_PARAMS.items():
            if param_name is None:
                continue
            try:
                resp = ssm.get_parameter(Name=param_name)
                value = resp["Parameter"]["Value"]
                config[env_var] = value
                # Also set as env var so agent/main.py can read them
                os.environ[env_var] = value
            except Exception:
                pass
    except Exception as e:
        st.sidebar.warning(f"Could not read SSM parameters: {e}")

    # Fall back to env vars for anything SSM didn't provide
    for env_var in SSM_PARAMS:
        if env_var not in config:
            val = os.environ.get(env_var, "")
            if val:
                config[env_var] = val

    return config


# ── Load config at startup ────────────────────────────────────────────
config = load_config_from_ssm()

# ── Page Setup ────────────────────────────────────────────────────────
st.set_page_config(page_title="ClimateRAG", page_icon="🌍", layout="wide")
st.title("🌍 ClimateRAG — Climate Trend Analysis")
st.caption("Powered by Amazon Bedrock AgentCore • NOAA GHCN v4 • NASA GISTEMP v4 • NASA POWER")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

with st.sidebar:
    st.header("📊 Datasets")
    st.markdown(
        "- 🌡️ **NOAA GHCN v4** — US station temps\n"
        "- 🌐 **NASA GISTEMP v4** — Global anomalies\n"
        "- ☀️ **NASA POWER** — Solar, precip, temp"
    )
    st.divider()
    st.header("💡 Try asking")
    st.markdown(
        "- *How has temperature changed in the Southeast?*\n"
        "- *Compare New York and LA trends since 1950*\n"
        "- *Plot global temperature anomalies*\n"
        "- *Warmest decades on record globally*"
    )
    st.divider()

    # Show config status
    st.header("⚙️ Config")
    memory_id = config.get("CLIMATE_RAG_MEMORY_ID", "")
    ci_id = config.get("CLIMATE_RAG_CODE_INTERPRETER_ID", "")
    if memory_id:
        st.text(f"Memory: ✅ {memory_id[:20]}...")
    else:
        st.text("Memory: ❌ Not configured")
    if ci_id:
        st.text(f"CodeInterp: ✅ {ci_id[:20]}...")
    else:
        st.text("CodeInterp: ❌ Not configured")

    st.divider()
    if st.button("🔄 New Session"):
        st.session_state.messages = []
        st.session_state.session_id = str(uuid.uuid4())
        st.rerun()


@st.cache_resource
def load_handler():
    """Load the agent request handler."""
    from main import handle_request

    return handle_request


# Render chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        for chart_path in msg.get("charts", []):
            if os.path.exists(chart_path):
                st.image(chart_path, use_container_width=True)

# Chat input
if prompt := st.chat_input("Ask about climate trends..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing climate data..."):
            try:
                handle_request = load_handler()
                result = handle_request(prompt, st.session_state.session_id)

                text = result["response"]
                charts = result.get("charts", [])
                guardrail_action = result.get("guardrail_action", "NONE")
                tools_called = result.get("tools_called", [])

                # Show guardrail block notice if triggered
                if guardrail_action in ("INPUT_BLOCKED", "OUTPUT_BLOCKED"):
                    st.warning(f"🛡️ Guardrail action: {guardrail_action}")

                # Show response
                st.markdown(text)

                # Show charts inline
                for chart_path in charts:
                    if os.path.exists(chart_path):
                        st.image(chart_path, use_container_width=True)

                # Show metadata expander with confidence and tools used
                with st.expander("📋 Response metadata", expanded=False):
                    if tools_called:
                        st.caption(f"**Tools used:** {', '.join(set(tools_called))}")
                    if guardrail_action != "NONE":
                        st.caption(f"**Guardrail:** {guardrail_action}")
                    st.caption(f"**Session:** {st.session_state.session_id[:8]}...")

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": text,
                    "charts": charts,
                })
            except Exception as e:
                st.error(f"Error: {e}")
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"Error: {e}", "charts": []}
                )
