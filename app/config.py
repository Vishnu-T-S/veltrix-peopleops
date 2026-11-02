"""Runtime settings, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Mapping, Optional

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_iso_date(value: str) -> date:
    """Parse a strict YYYY-MM-DD string. Raises ValueError for anything else."""
    if not isinstance(value, str) or not _ISO_DATE.match(value.strip()):
        raise ValueError(f"not a YYYY-MM-DD date: {value!r}")
    return date.fromisoformat(value.strip())


@dataclass(frozen=True)
class Settings:
    corpus_dir: str
    manifest_path: str
    db_path: str
    app_today: date
    llm_provider: str
    openai_api_key: Optional[str]
    openai_model: Optional[str]
    openai_embedding_model: Optional[str]


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    env = os.environ if env is None else env

    def get(name: str, default: Optional[str] = None) -> Optional[str]:
        value = env.get(name)
        return value if value not in (None, "") else default

    raw_today = get("APP_TODAY")
    today = parse_iso_date(raw_today) if raw_today else date.today()

    return Settings(
        corpus_dir=get("CORPUS_DIR", "./data/corpus"),
        manifest_path=get("MANIFEST_PATH", "./data/manifest.json"),
        db_path=get("DB_PATH", "./data/veltrix.db"),
        app_today=today,
        llm_provider=get("LLM_PROVIDER", "openai"),
        openai_api_key=get("OPENAI_API_KEY"),
        openai_model=get("OPENAI_MODEL"),
        openai_embedding_model=get("OPENAI_EMBEDDING_MODEL"),
    )
