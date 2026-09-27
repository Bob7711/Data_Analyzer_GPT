"""Builds the two AutoGen teams.

full  - DataLoader -> DataCleaner -> FeatureEngineer -> DataAnalyzer -> Visualizer
        -> ReportGenerator, each code-writing stage looping with the CodeExecutor until
        its code succeeds (deterministic routing, no LLM speaker selection).
quick - Data Analyzer GPT + CodeExecutor in a RoundRobinGroupChat.
"""

from typing import Sequence

from autogen_agentchat.agents import AssistantAgent, CodeExecutorAgent
from autogen_agentchat.base import Team
from autogen_agentchat.conditions import (
    MaxMessageTermination,
    SourceMatchTermination,
    TextMentionTermination,
)
from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage
from autogen_agentchat.teams import RoundRobinGroupChat, SelectorGroupChat
from autogen_core.code_executor import CodeExecutor
from autogen_core.models import ChatCompletionClient

from . import prompts
from .config import settings

EXECUTOR_NAME = "CodeExecutor"
PIPELINE: list[tuple[str, str, str]] = [
    ("DataLoader", "Loads the CSV and profiles its schema.", prompts.DATA_LOADER),
    ("DataCleaner", "Cleans the data and writes cleaned.csv.", prompts.DATA_CLEANER),
    ("FeatureEngineer", "Derives features and writes features.csv.", prompts.FEATURE_ENGINEER),
    ("DataAnalyzer", "Computes statistics that answer the question.", prompts.DATA_ANALYZER),
    ("Visualizer", "Draws charts and saves them as PNG files.", prompts.VISUALIZER),
    ("ReportGenerator", "Writes the final Markdown report.", prompts.REPORT_GENERATOR),
]
STAGES = [name for name, _, _ in PIPELINE]
FINAL_AGENT = STAGES[-1]
# Code/fix attempts a stage gets before the pipeline moves on regardless.
MAX_CODE_ROUNDS = 5
# Code-free replies a stage may give before any of its code has run.
MAX_PLAN_ONLY_TURNS = 3


def _executor_agent(executor: CodeExecutor) -> CodeExecutorAgent:
    return CodeExecutorAgent(
        EXECUTOR_NAME,
        code_executor=executor,
        description="Executes Python/shell code blocks and returns the output.",
    )


def _has_code(message: BaseChatMessage) -> bool:
    return "```" in message.to_text()


def pipeline_selector(thread: Sequence[BaseAgentEvent | BaseChatMessage]) -> str | None:
    messages = [m for m in thread if isinstance(m, BaseChatMessage)]
    last = messages[-1]

    if last.source not in STAGES and last.source != EXECUTOR_NAME:
        return STAGES[0]  # the user's task starts the pipeline

    stage = next((m.source for m in reversed(messages) if m.source in STAGES), None)
    if stage is None:
        return STAGES[0]

    # The current stage's turn: trailing messages from that stage and the executor.
    runs = turns = 0
    for message in reversed(messages):
        if message.source == EXECUTOR_NAME:
            runs += 1
        elif message.source == stage:
            turns += 1
        else:
            break

    if last.source == EXECUTOR_NAME:
        return stage  # let the stage read the output and fix or summarise
    if _has_code(last) and runs < MAX_CODE_ROUNDS:
        return EXECUTOR_NAME
    if runs == 0 and stage != FINAL_AGENT and turns < MAX_PLAN_ONLY_TURNS:
        return stage  # it only described a plan; its work must actually run before handing off
    index = STAGES.index(stage)
    return STAGES[index + 1] if index + 1 < len(STAGES) else None


def build_full_team(model_client: ChatCompletionClient, executor: CodeExecutor) -> Team:
    agents = [
        AssistantAgent(name, model_client=model_client, description=description, system_message=prompt)
        for name, description, prompt in PIPELINE
    ]
    termination = SourceMatchTermination([FINAL_AGENT]) | MaxMessageTermination(settings.max_messages)
    return SelectorGroupChat(
        [*agents, _executor_agent(executor)],
        model_client=model_client,
        selector_func=pipeline_selector,
        termination_condition=termination,
    )


def build_quick_team(model_client: ChatCompletionClient, executor: CodeExecutor) -> Team:
    analyst = AssistantAgent(
        "DataAnalyzerGPT",
        model_client=model_client,
        description="Writes Python code to analyse the dataset.",
        system_message=prompts.QUICK_ANALYST,
    )
    termination = TextMentionTermination("TERMINATE", sources=[analyst.name]) | MaxMessageTermination(
        settings.max_messages
    )
    return RoundRobinGroupChat([analyst, _executor_agent(executor)], termination_condition=termination)
