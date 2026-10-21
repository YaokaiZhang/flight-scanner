"""Which notifiers exist and how to build them from settings (FS_NOTIFIERS).

To add a channel: implement `Notifier` in `notify/<channel>.py` and register a factory here.
"""

from __future__ import annotations

from collections.abc import Callable

from flight_scanner.config import Settings
from flight_scanner.notify.base import LogNotifier, Notifier

FACTORIES: dict[str, Callable[[Settings], Notifier]] = {
    "log": lambda settings: LogNotifier(),
}


def build_notifiers(settings: Settings) -> list[Notifier]:
    unknown = set(settings.notifiers) - FACTORIES.keys()
    if unknown:
        raise ValueError(f"unknown notifiers in FS_NOTIFIERS: {sorted(unknown)}")
    return [FACTORIES[name](settings) for name in settings.notifiers]
