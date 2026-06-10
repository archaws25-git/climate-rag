"""ClimateRAG — Evaluation Dashboard.

Displays the latest eval results from eval/results/ as an interactive
Streamlit dashboard with metric cards, per-query tables, and latency charts.

Access via Streamlit multipage nav or http://localhost:8501/eval_dashboard
"""

import glob
import json
import os

import streamlit as st

st.set_page_config(page_title="ClimateRAG — Eval Dashboard", page_icon="📊", layout="wide")
st.title("📊 ClimateRAG — Evaluation Dashboard")

# ── Find latest eval results ──────────────────────────────────────────────────
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "eval", "results")
result_files = sorted(glob.glob(os.path.join(RESULTS_DIR, "eval_*.json")), reverse=True)

if not result_files:
    st.warning("No eval results found. Run `python eval/run.py` first.")
    st.stop()

# Let user select which report to view
selected_file = st.selectbox(
    "Select eval report",
    result_files,
    format_func=lambda x: os.path.basename(x),
)

with open(selected_file, encoding="utf-8") as f:
    report = json.load(f)

# ── Metadata ──────────────────────────────────────────────────────────────────
meta = report.get("metadata", {})
st.caption(
    f"**Timestamp:** {meta.get('timestamp', 'N/A')} | "
    f"**Suites:** {', '.join(meta.get('suites', []))} | "
    f"**Judge:** {meta.get('judge_model', 'N/A')}"
)

st.divider()

suites = report.get("suites", {})

# ── Retrieval Suite ───────────────────────────────────────────────────────────
if "retrieval" in suites:
    st.header("🔍 Retrieval Quality")
    ret = suites["retrieval"]
    summary = ret.get("summary", {})

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        val = summary.get("avg_recall", 0)
        st.metric("Recall@K", f"{val:.0%}", delta="✅" if val >= 0.9 else "❌")
    with col2:
        val = summary.get("avg_precision", 0)
        st.metric("Precision@K", f"{val:.0%}", delta="✅" if val >= 0.9 else "❌")
    with col3:
        val = summary.get("avg_mrr", 0)
        st.metric("MRR", f"{val:.3f}", delta="✅" if val >= 0.9 else "❌")
    with col4:
        val = summary.get("avg_ndcg", 0)
        st.metric("NDCG@K", f"{val:.3f}", delta="✅" if val >= 0.9 else "❌")

    # Per-query table
    results = ret.get("results", [])
    if results:
        with st.expander(f"Per-query results ({len(results)} queries)", expanded=False):
            st.dataframe(results, use_container_width=True)

    st.divider()

# ── E2E Suite ─────────────────────────────────────────────────────────────────
if "e2e" in suites:
    st.header("🎯 End-to-End Quality (LLM-as-Judge)")
    e2e = suites["e2e"]
    summary = e2e.get("summary", {})

    col1, col2, col3 = st.columns(3)
    with col1:
        val = summary.get("avg_composite", 0)
        st.metric("Composite Score", f"{val:.0%}", delta="✅" if val >= 0.9 else "❌")
    with col2:
        val = summary.get("pass_rate", 0)
        st.metric("Pass Rate", f"{val:.0%}")
    with col3:
        val = summary.get("avg_latency_s", 0)
        st.metric("Avg Latency", f"{val:.1f}s")

    # Latency percentiles
    latency = summary.get("latency", {})
    if latency:
        lcol1, lcol2, lcol3 = st.columns(3)
        with lcol1:
            st.metric("E2E P50", f"{latency.get('p50', 0)/1000:.1f}s")
        with lcol2:
            st.metric("E2E P95", f"{latency.get('p95', 0)/1000:.1f}s")
        with lcol3:
            st.metric("E2E P99", f"{latency.get('p99', 0)/1000:.1f}s")

    # Per-query results
    results = e2e.get("results", [])
    if results:
        successful = [r for r in results if r.get("status") == "success"]
        failed = [r for r in results if r.get("status") != "success"]

        with st.expander(f"Per-query scores ({len(successful)} passed, {len(failed)} failed)", expanded=False):
            for r in successful:
                scores = r.get("scores", {})
                status = "✅" if r.get("composite", 0) >= 0.9 else "⚠️"
                st.text(
                    f"{status} [{r['id']}] composite={r.get('composite', 0):.0%} "
                    f"correctness={scores.get('correctness', 0)}/5 "
                    f"relevance={scores.get('relevance', 0)}/5 "
                    f"latency={r.get('latency_s', 0):.1f}s"
                )
            for r in failed:
                st.text(f"❌ [{r.get('id', '?')}] {r.get('error', 'Unknown error')}")

    st.divider()

# ── Multi-Turn Suite ──────────────────────────────────────────────────────────
if "multiturn" in suites:
    st.header("🔄 Multi-Turn Coherence")
    mt = suites["multiturn"]
    summary = mt.get("summary", {})

    col1, col2, col3 = st.columns(3)
    with col1:
        val = summary.get("avg_context_resolution", 0)
        st.metric("Context Resolution", f"{val:.1f}/5", delta="✅" if val >= 4.0 else "❌")
    with col2:
        val = summary.get("avg_session_coherence", 0)
        st.metric("Session Coherence", f"{val:.1f}/5", delta="✅" if val >= 4.0 else "❌")
    with col3:
        val = summary.get("avg_progressive_quality", 0)
        st.metric("Progressive Quality", f"{val:.1f}/5", delta="✅" if val >= 4.0 else "❌")

    # Per-flow details
    results = mt.get("results", [])
    if results:
        with st.expander(f"Per-flow results ({len(results)} flows)", expanded=False):
            for r in results:
                scores = r.get("scores", {})
                st.text(
                    f"[{r.get('flow_id', '?')}] {r.get('flow_name', '')} — "
                    f"context={scores.get('context_resolution', 0)}/5 "
                    f"coherence={scores.get('session_coherence', 0)}/5"
                )

    st.divider()

# ── Latency Suite ─────────────────────────────────────────────────────────────
if "latency" in suites:
    st.header("⏱️ Latency Performance")
    lat = suites["latency"]
    summary = lat.get("summary", {})
    e2e_stats = summary.get("e2e", {})

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("P50", f"{e2e_stats.get('p50', 0)/1000:.1f}s")
    with col2:
        st.metric("P95", f"{e2e_stats.get('p95', 0)/1000:.1f}s")
    with col3:
        st.metric("P99", f"{e2e_stats.get('p99', 0)/1000:.1f}s")
    with col4:
        st.metric("Mean", f"{e2e_stats.get('mean', 0)/1000:.1f}s")

    # Per-query latencies as a bar chart
    results = lat.get("results", [])
    if results:
        latencies = [r.get("e2e_ms", 0) / 1000 for r in results if r.get("status") == "ok"]
        queries = [r.get("query", "")[:30] for r in results if r.get("status") == "ok"]
        if latencies:
            import pandas as pd
            chart_data = pd.DataFrame({"Query": queries, "Latency (s)": latencies})
            st.bar_chart(chart_data.set_index("Query"))

    st.divider()

# ── Historical Trend ──────────────────────────────────────────────────────────
if len(result_files) > 1:
    st.header("📈 Historical Trend")

    trend_data = []
    for fp in result_files[:10]:  # Last 10 runs
        try:
            with open(fp, encoding="utf-8") as f:
                r = json.load(f)
            ts = r.get("metadata", {}).get("timestamp", "")[:16]
            e2e_suite = r.get("suites", {}).get("e2e", {}).get("summary", {})
            ret_suite = r.get("suites", {}).get("retrieval", {}).get("summary", {})
            trend_data.append({
                "Run": ts,
                "Composite": e2e_suite.get("avg_composite", 0),
                "Recall": ret_suite.get("avg_recall", 0),
            })
        except Exception:
            continue

    if trend_data:
        import pandas as pd
        df = pd.DataFrame(trend_data)
        if not df.empty:
            st.line_chart(df.set_index("Run"))

st.caption("Run `python eval/run.py` to generate new results.")
