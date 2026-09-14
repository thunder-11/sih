"""Compatibility entry point for `uvicorn main:app`."""

from app.main import app, create_app
from app.realtime import ws_manager

__all__ = ["app", "create_app", "ws_manager"]
