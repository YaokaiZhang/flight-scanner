"""ASGI entry point: `uvicorn flight_scanner.api.main:app` (settings from the environment)."""

from flight_scanner.api.app import create_app
from flight_scanner.clock import SystemClock
from flight_scanner.config import Settings
from flight_scanner.data_health import VerificationBudget
from flight_scanner.db import migrate
from flight_scanner.sources.registry import build_verifier

_settings = Settings.from_env()
migrate(_settings.db)
_verifier = build_verifier(_settings, SystemClock())  # only its name and quota are used
app = create_app(
    _settings.db,
    verification_budget=None
    if _verifier is None
    else VerificationBudget(_verifier.name, _verifier.daily_quota, _verifier.monthly_quota),
)
