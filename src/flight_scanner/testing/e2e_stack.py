"""Backend for the Playwright smoke test (and for poking at the UI by hand).

python -m flight_scanner.testing.e2e_stack serve --state-dir .e2e --port 18000
    ephemeral Postgres + migrations + the HTTP API on 127.0.0.1:<port>; Ctrl-C/SIGTERM stops all
python -m flight_scanner.testing.e2e_stack scan --state-dir .e2e --payload-dir DIR --at ISO
    one in-process pipeline run against that database, with a fake source replaying DIR
    (`<ORIGIN>-<DESTINATION>*.json` files) and the clock fixed at --at; prints Alerts as JSON;
    --deal-context TEXT turns on a fake Deal-context researcher answering TEXT for every Deal
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from flight_scanner.clock import FakeClock
from flight_scanner.db import DbSettings
from flight_scanner.notify.base import RecordingNotifier
from flight_scanner.raw_store import RawStore
from flight_scanner.sources.replay import ReplayAdapter


def serve(state_dir: Path, port: int) -> None:
    import uvicorn

    from flight_scanner.api import create_app
    from flight_scanner.testing.ephemeral_pg import EphemeralPostgres

    state_dir.mkdir(parents=True, exist_ok=True)
    pg = EphemeralPostgres.start()
    try:
        db = pg.clone(pg.create_template())
        (state_dir / "db.json").write_text(json.dumps(asdict(db)))
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        uvicorn.run(create_app(db), host="127.0.0.1", port=port, log_level="warning")
    finally:
        pg.stop()


def scan(state_dir: Path, payload_dir: Path, at: datetime, deal_context: str | None = None) -> None:
    from flight_scanner.pipeline import Runtime, run_once
    from flight_scanner.testing.fake_researcher import FakeResearcher

    db = DbSettings(**json.loads((state_dir / "db.json").read_text()))
    clock = FakeClock(at)
    notifier = RecordingNotifier()
    runtime = Runtime(
        clock=clock,
        db=db,
        raw_store=RawStore(state_dir / "raw"),
        work_dir=state_dir / "work",
        sources=[ReplayAdapter.from_dir("fake", clock, payload_dir)],
        notifiers=[notifier],
        researcher=FakeResearcher(default=deal_context) if deal_context else None,
    )
    result = run_once(runtime)
    print(json.dumps([asdict(a) for a in notifier.alerts], default=str))
    sys.exit(0 if result.success else 1)


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--state-dir", type=Path, required=True)
    s.add_argument("--port", type=int, required=True)
    c = sub.add_parser("scan")
    c.add_argument("--state-dir", type=Path, required=True)
    c.add_argument("--payload-dir", type=Path, required=True)
    c.add_argument("--at", type=datetime.fromisoformat, required=True)
    c.add_argument("--deal-context")
    a = p.parse_args()
    if a.cmd == "serve":
        serve(a.state_dir, a.port)
    else:
        scan(a.state_dir, a.payload_dir, a.at, a.deal_context)


if __name__ == "__main__":
    main()
