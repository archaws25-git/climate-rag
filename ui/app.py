"""ClimateRAG — Streamlit Chat UI with inline chart rendering."""

import os
import sys
import uuid

import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))

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
    if st.button("🔄 New Session"):
        st.session_state.messages = []
        st.session_state.session_id = str(uuid.uuid4())
        st.rerun()


@st.cache_resource
def load_handler():
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

                st.markdown(text)
                for chart_path in charts:
                    if os.path.exists(chart_path):
                        st.image(chart_path, use_container_width=True)

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
