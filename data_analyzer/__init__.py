"""AutoGen Data Analyzer GPT: a team of AI agents that analyses CSV files."""

from .pipeline import AgentMessage, AnalysisResult, run_analysis

__all__ = ["AgentMessage", "AnalysisResult", "run_analysis"]
