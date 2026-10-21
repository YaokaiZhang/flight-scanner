"""HTTP API (FastAPI). Reads Watches and marts; never writes pipeline-owned tables."""

from flight_scanner.api.app import create_app

__all__ = ["create_app"]
