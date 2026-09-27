"""Central settings, read from environment variables / .env."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    # "auto" -> Docker if the daemon is reachable, otherwise local subprocess.
    executor: str = field(default_factory=lambda: os.getenv("CODE_EXECUTOR", "auto"))
    docker_image: str = field(default_factory=lambda: os.getenv("DOCKER_IMAGE", "amancevice/pandas:2.2.2"))
    code_timeout: int = field(default_factory=lambda: int(os.getenv("CODE_TIMEOUT", "120")))
    work_root: Path = field(default_factory=lambda: PROJECT_ROOT / os.getenv("WORK_DIR", "temp"))
    max_messages: int = field(default_factory=lambda: int(os.getenv("MAX_MESSAGES", "80")))


settings = Settings()
