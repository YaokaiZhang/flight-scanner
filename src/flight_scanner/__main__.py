"""`python -m flight_scanner migrate|scan` - operational one-offs."""

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
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
