"""ASGI entrypoint: `uvicorn app.main:app`."""
from app.interfaces.app import app

__all__ = ["app"]
