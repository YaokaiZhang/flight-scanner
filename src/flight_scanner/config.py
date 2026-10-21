"""Settings, all from environment variables (see `.env.example`). Nothing secret is committed."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from flight_scanner.db import DbSettings


def _list(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    db: DbSettings
    raw_dir: Path
    work_dir: Path
    sources: list[str] = field(default_factory=list)
    notifiers: list[str] = field(default_factory=lambda: ["log"])
    env: dict[str, str] = field(default_factory=dict)  # for adapter/notifier factories

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ if env is None else env)
        data = Path(env.get("FS_DATA_DIR", "data"))
        return cls(
            db=DbSettings.from_env(env),
            raw_dir=Path(env.get("FS_RAW_DIR", data / "raw")),
            work_dir=Path(env.get("FS_WORK_DIR", data / "work")),
            sources=_list(env.get("FS_SOURCES")),
            notifiers=_list(env.get("FS_NOTIFIERS", "log")),
            env=env,
        )
