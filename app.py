"""Streamlit chat UI for the AutoGen Data Analyzer GPT.

Run with:  streamlit run app.py
"""

import asyncio
from pathlib import Path

import pandas as pd
import streamlit as st

from data_analyzer import AgentMessage, AnalysisResult, run_analysis
from data_analyzer.config import settings
from data_analyzer.executor import docker_available
from data_analyzer.pipeline import new_work_dir

AVATARS = {
    "DataLoader": "📥",
    "DataCleaner": "🧹",
    "FeatureEngineer": "⚙️",
    "DataAnalyzer": "📊",
    "DataAnalyzerGPT": "📊",
    "Visualizer": "🖼️",
    "ReportGenerator": "📝",
    "CodeExecutor": "🐍",
}
MODES = {
    "Full pipeline (6 specialist agents)": "full",
    "Quick (Analyzer + Code Executor)": "quick",
}

st.set_page_config(page_title="Data Analyzer GPT", page_icon="📊", layout="wide")
st.session_state.setdefault("turns", [])


def render_message(source: str, content: str) -> None:
    with st.chat_message(source, avatar=AVATARS.get(source, "🤖")):
        st.markdown(f"**{source}**")
        if source == "CodeExecutor":
            with st.expander("Execution output", expanded=False):
                st.code(content, language="text")
        else:
            st.markdown(content)


def render_result(report: str, plots: list[str], key: str) -> None:
    with st.chat_message("assistant", avatar="✅"):
        st.markdown(report)
        for plot in plots:
            if Path(plot).exists():
                st.image(plot, caption=Path(plot).name)
        st.download_button("Download report (.md)", report, file_name="report.md", key=f"dl-{key}")


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("📊 Data Analyzer GPT")
    st.caption("Microsoft AutoGen agents analyse your CSV from a plain-English question.")

    api_key = st.text_input("OpenAI API key", value=settings.openai_api_key, type="password")
    model = st.text_input("Model", value=settings.model)
    mode = MODES[st.radio("Agent team", list(MODES))]

    has_docker = docker_available()
    executor_mode = st.selectbox(
        "Code execution",
        ["docker", "local"] if has_docker else ["local", "docker"],
        help=f"Docker runs code in `{settings.docker_image}`; local runs it in this Python environment.",
    )
    if not has_docker:
        st.info("Docker isn't reachable, so agent-written code will run locally on this machine.")

    uploaded = st.file_uploader("Upload a CSV file", type=["csv"])
    if st.button("Clear conversation"):
        st.session_state.turns = []
        st.rerun()

# ---------------------------------------------------------------- main area
st.header("Ask questions about your data")

if uploaded is not None:
    try:
        preview = pd.read_csv(uploaded, nrows=200)
        uploaded.seek(0)
        with st.expander(f"Preview: {uploaded.name} ({preview.shape[1]} columns)", expanded=False):
            st.dataframe(preview.head(20), width="stretch")
    except Exception as error:
        st.error(f"Couldn't read this CSV: {error}")

for index, turn in enumerate(st.session_state.turns):
    with st.chat_message("user"):
        st.markdown(turn["question"])
    for source, content in turn["messages"]:
        render_message(source, content)
    render_result(turn["report"], turn["plots"], key=str(index))

question = st.chat_input("e.g. What are the monthly sales trends and which region performs best?")

if question:
    if uploaded is None:
        st.warning("Upload a CSV file in the sidebar first.")
        st.stop()
    if not api_key:
        st.warning("Enter your OpenAI API key in the sidebar.")
        st.stop()

    with st.chat_message("user"):
        st.markdown(question)

    work_dir = new_work_dir()
    csv_path = work_dir / Path(uploaded.name).name
    csv_path.write_bytes(uploaded.getvalue())

    turn = {"question": question, "messages": [], "report": "", "plots": []}

    async def consume() -> None:
        stream = run_analysis(
            csv_path, question, mode=mode, executor_mode=executor_mode,
            work_dir=work_dir, api_key=api_key, model=model,
        )
        async for item in stream:
            if isinstance(item, AgentMessage):
                turn["messages"].append((item.source, item.content))
                render_message(item.source, item.content)
            elif isinstance(item, AnalysisResult):
                turn["report"] = item.report
                turn["plots"] = [str(p) for p in item.plots]

    status = st.status("Agents are working…", expanded=False)
    try:
        asyncio.run(consume())
        status.update(label="Analysis complete", state="complete")
    except Exception as error:
        status.update(label="Analysis failed", state="error")
        st.exception(error)
        st.stop()

    render_result(turn["report"], turn["plots"], key=str(len(st.session_state.turns)))
    st.session_state.turns.append(turn)
