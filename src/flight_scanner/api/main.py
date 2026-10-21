"""ASGI entry point: `uvicorn flight_scanner.api.main:app` (settings from the environment)."""

from flight_scanner.api.app import create_app
from flight_scanner.config import Settings
from flight_scanner.db import migrate

_settings = Settings.from_env()
migrate(_settings.db)
app = create_app(_settings.db)
