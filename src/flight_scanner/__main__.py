"""`python -m flight_scanner migrate|scan|rebuild|unblock <source>` - operational one-offs.

rebuild: re-parse every raw payload of the enabled sources and rebuild staging, history and marts.
unblock: re-enable a source that disabled itself after being turned away (GET /sources/blocked).
"""

import sys

from flight_scanner.config import Settings
from flight_scanner.db import migrate


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "migrate":
        print("applied:", migrate(Settings.from_env().db) or "nothing")
        return 0
    if cmd == "scan":
        from flight_scanner.pipeline import run_once
        from flight_scanner.pipeline.workspace import runtime_from_env

        runtime = runtime_from_env()
        migrate(runtime.db)
        return 0 if run_once(runtime).success else 1
    if cmd == "rebuild":
        from flight_scanner.pipeline import rebuild
        from flight_scanner.pipeline.workspace import runtime_from_env

        runtime = runtime_from_env()
        migrate(runtime.db)
        print(rebuild(runtime))
        return 0
    if cmd == "unblock" and len(argv) == 3:
        from flight_scanner import source_health
        from flight_scanner.db import connect

        settings = Settings.from_env()
        migrate(settings.db)
        with connect(settings.db) as conn:
            done = source_health.unblock(conn, argv[2])
        print(f"{argv[2]}: {'re-enabled' if done else 'was not blocked'}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
