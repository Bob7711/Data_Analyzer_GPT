"""Command-line runner.

Example:
    python main.py sample_data/sales.csv "Which region has the highest revenue growth?" --mode quick
"""

import argparse
import asyncio
from pathlib import Path

from data_analyzer import AgentMessage, AnalysisResult, run_analysis


async def main() -> None:
    parser = argparse.ArgumentParser(description="AutoGen Data Analyzer GPT")
    parser.add_argument("csv", type=Path, help="Path to the CSV file")
    parser.add_argument("question", help="Question about the data, in plain English")
    parser.add_argument("--mode", choices=["full", "quick"], default="full")
    parser.add_argument("--executor", choices=["auto", "docker", "local"], default=None)
    args = parser.parse_args()

    async for item in run_analysis(args.csv, args.question, mode=args.mode, executor_mode=args.executor):
        if isinstance(item, AgentMessage):
            print(f"\n---------- {item.source} ----------\n{item.content}")
        elif isinstance(item, AnalysisResult):
            print("\n========== FINAL REPORT ==========\n" + item.report)
            print(f"\nExecutor: {item.executor_mode} | Stop reason: {item.stop_reason}")
            print(f"Work dir: {item.work_dir}")
            for plot in item.plots:
                print(f"Plot: {plot}")


if __name__ == "__main__":
    asyncio.run(main())
