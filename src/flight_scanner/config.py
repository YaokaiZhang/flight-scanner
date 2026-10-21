"""Settings, all from environment variables (see `.env.example`). Nothing secret is committed."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from flight_scanner.db import DbSettings
from flight_scanner.scan_planner import Budget


def _list(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def parse_budgets(value: str | None) -> dict[str, Budget]:
    """`travelpayouts=200/run+5000/day,fake=50/run` -> {source: Budget}."""
    budgets: dict[str, Budget] = {}
    for item in _list(value):
        source, _, limits = item.partition("=")
        per: dict[str, int] = {}
        for limit in limits.split("+"):
            n, _, unit = limit.strip().partition("/")
            if unit not in ("run", "day") or not n.strip().isdigit():
                raise ValueError(f"FS_SCAN_BUDGETS: bad limit {limit!r} (use N/run or N/day)")
            per[unit] = int(n)
        budgets[source.strip()] = Budget(per_run=per.get("run"), per_day=per.get("day"))
    return budgets


@dataclass(frozen=True)
class Settings:
    db: DbSettings
    raw_dir: Path
    work_dir: Path
    sources: list[str] = field(default_factory=list)
    notifiers: list[str] = field(default_factory=lambda: ["log"])
    source_budgets: dict[str, Budget] = field(default_factory=dict)
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
            source_budgets=parse_budgets(env.get("FS_SCAN_BUDGETS")),
            env=env,
        )
