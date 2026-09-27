"""Runs one analysis and streams the agents' messages as they arrive."""

import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Literal

from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import BaseChatMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient

from .config import settings
from .executor import create_executor, prepare_executor, resolve_mode
from .prompts import DATA_FILE
from .team import FINAL_AGENT, build_full_team, build_quick_team

Mode = Literal["full", "quick"]


@dataclass
class AgentMessage:
    source: str
    content: str


@dataclass
class AnalysisResult:
    work_dir: Path
    executor_mode: str
    report: str
    plots: list[Path] = field(default_factory=list)
    stop_reason: str | None = None


def new_work_dir(root: Path | None = None) -> Path:
    work_dir = (root or settings.work_root) / uuid.uuid4().hex[:10]
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _final_report(messages: list[AgentMessage], mode: Mode) -> str:
    author = FINAL_AGENT if mode == "full" else "DataAnalyzerGPT"
    for message in reversed(messages):
        if message.source == author and "```" not in message.content:
            return message.content.replace("TERMINATE", "").strip()
    return "The agents did not produce a final report. See the conversation above for details."


async def run_analysis(
    csv_path: Path,
    question: str,
    *,
    mode: Mode = "full",
    executor_mode: str | None = None,
    work_dir: Path | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> AsyncIterator[AgentMessage | AnalysisResult]:
    """Yields each agent message, then a final AnalysisResult."""
    work_dir = work_dir or new_work_dir()
    target = work_dir / DATA_FILE
    if Path(csv_path).resolve() != target.resolve():
        shutil.copy(csv_path, target)

    resolved = resolve_mode(executor_mode)
    executor = create_executor(work_dir, resolved)
    model_client = OpenAIChatCompletionClient(
        model=model or settings.model,
        api_key=api_key or settings.openai_api_key,
    )
    team = (build_full_team if mode == "full" else build_quick_team)(model_client, executor)
    task = (
        f"Dataset file: `{DATA_FILE}` (uploaded as `{Path(csv_path).name}`).\n"
        f"User question: {question}"
    )

    messages: list[AgentMessage] = []
    stop_reason = None
    try:
        await prepare_executor(executor, resolved)
        async for item in team.run_stream(task=task):
            if isinstance(item, TaskResult):
                stop_reason = item.stop_reason
            elif isinstance(item, BaseChatMessage) and item.source != "user":
                message = AgentMessage(item.source, item.to_text())
                messages.append(message)
                yield message
    finally:
        await executor.stop()
        await model_client.close()

    yield AnalysisResult(
        work_dir=work_dir,
        executor_mode=resolved,
        report=_final_report(messages, mode),
        plots=sorted(work_dir.glob("*.png")),
        stop_reason=stop_reason,
    )
