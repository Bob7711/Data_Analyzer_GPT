"""Code executor factory: Docker sandbox when available, local subprocess otherwise."""

import os
import re
import shlex
import sys
from pathlib import Path
from typing import List

from autogen_core import CancellationToken
from autogen_core.code_executor import CodeBlock, CodeExecutor
from autogen_ext.code_executors._common import CommandLineCodeResult
from autogen_ext.code_executors.local import LocalCommandLineCodeExecutor

from .config import settings

# Headless plotting for any Python process the executor spawns.
os.environ.setdefault("MPLBACKEND", "Agg")

# Packages the agents rely on that the pandas image does not ship with.
DOCKER_EXTRA_PACKAGES = "matplotlib seaborn scipy"

SHELL_LANGUAGES = {"sh", "bash", "shell", "console"}
PIP_COMMAND = re.compile(r"^\s*!?(?:python3?\s+-m\s+)?pip3?\s+(.+)$")


class SafeLocalExecutor(LocalCommandLineCodeExecutor):
    """Local executor that works on Windows and never crashes the team.

    - `pip ...` lines in shell blocks run through this interpreter's pip, so packages
      land in the same environment the agents' Python code runs in.
    - Other shell blocks run in PowerShell on Windows, where `sh` does not exist.
    - Execution failures are returned to the agent as an error result to fix.
    """

    def _translate(self, block: CodeBlock) -> CodeBlock:
        if block.language.lower() not in SHELL_LANGUAGES:
            return block
        lines = [line for line in block.code.splitlines() if line.strip() and not line.strip().startswith("#")]
        pip_args = [PIP_COMMAND.match(line) for line in lines]
        if lines and all(pip_args):
            calls = "\n".join(
                f"subprocess.run([sys.executable, '-m', 'pip', *{shlex.split(m.group(1))!r}], check=False)"
                for m in pip_args
            )
            return CodeBlock(code=f"import subprocess, sys\n{calls}", language="python")
        if sys.platform == "win32":
            return CodeBlock(code=block.code, language="powershell")
        return block

    async def execute_code_blocks(
        self, code_blocks: List[CodeBlock], cancellation_token: CancellationToken
    ) -> CommandLineCodeResult:
        try:
            return await super().execute_code_blocks(
                [self._translate(block) for block in code_blocks], cancellation_token
            )
        except Exception as error:
            return CommandLineCodeResult(
                exit_code=1,
                output=f"Execution failed: {type(error).__name__}: {error}. Use a ```python block instead.",
                code_file=None,
            )


def docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


def resolve_mode(mode: str | None = None) -> str:
    mode = (mode or settings.executor).lower()
    if mode == "auto":
        return "docker" if docker_available() else "local"
    if mode not in ("docker", "local"):
        raise ValueError(f"Unknown executor mode: {mode!r} (use auto, docker or local)")
    return mode


def create_executor(work_dir: Path, mode: str) -> CodeExecutor:
    if mode == "docker":
        from autogen_ext.code_executors.docker import DockerCommandLineCodeExecutor

        return DockerCommandLineCodeExecutor(
            image=settings.docker_image,
            work_dir=work_dir,
            timeout=settings.code_timeout,
        )
    return SafeLocalExecutor(work_dir=work_dir, timeout=settings.code_timeout)


async def prepare_executor(executor: CodeExecutor, mode: str) -> None:
    """Start the executor and install plotting libs inside the container."""
    await executor.start()
    if mode == "docker":
        await executor.execute_code_blocks(
            [CodeBlock(code=f"pip install -q {DOCKER_EXTRA_PACKAGES}", language="sh")],
            CancellationToken(),
        )
