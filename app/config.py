from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "sim", "on"}


def _as_optional_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        number = int(value)
    except ValueError as exc:
        raise RuntimeError("DEV_GUILD_ID deve ser um número inteiro.") from exc
    if number <= 0:
        raise RuntimeError("DEV_GUILD_ID deve ser um ID positivo.")
    return number


@dataclass(frozen=True, slots=True)
class Environment:
    token: str
    database_path: Path
    sync_commands_on_start: bool
    dev_guild_id: int | None
    log_level: str

    @classmethod
    def load(cls) -> "Environment":
        load_dotenv(override=False)
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise RuntimeError("DISCORD_TOKEN não foi definido no arquivo .env.")

        database_value = os.getenv("DATABASE_PATH", "data/skstore.db").strip()
        database_path = Path(database_value or "data/skstore.db")
        return cls(
            token=token,
            database_path=database_path,
            sync_commands_on_start=_as_bool(
                os.getenv("SYNC_COMMANDS_ON_START"), True
            ),
            dev_guild_id=_as_optional_int(os.getenv("DEV_GUILD_ID")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
