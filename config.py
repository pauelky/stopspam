from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent


def _path_from_env(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return BASE_DIR / path


def _required_int(name: str) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required in .env")
    return int(value)


def _required_str(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required in .env")
    return value


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    session_name: str
    owner_id: int
    database_path: Path
    clean_limit: int
    log_path: Path
    expire_check_seconds: int

    @property
    def session_path(self) -> Path:
        return BASE_DIR / "sessions" / self.session_name


def load_config() -> Config:
    load_dotenv(BASE_DIR / ".env")
    config = Config(
        api_id=_required_int("API_ID"),
        api_hash=_required_str("API_HASH"),
        session_name=os.getenv("SESSION_NAME", "chat_cleaner").strip() or "chat_cleaner",
        owner_id=_required_int("OWNER_ID"),
        database_path=_path_from_env(os.getenv("DATABASE_PATH", "./data/bot.db")),
        clean_limit=int(os.getenv("CLEAN_LIMIT", "50")),
        log_path=_path_from_env(os.getenv("LOG_PATH", "./logs/app.log")),
        expire_check_seconds=int(os.getenv("EXPIRE_CHECK_SECONDS", "45")),
    )
    config.database_path.parent.mkdir(parents=True, exist_ok=True)
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "sessions").mkdir(parents=True, exist_ok=True)
    return config
