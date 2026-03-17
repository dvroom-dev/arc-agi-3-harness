"""Shared model runtime used by agent-owned model.py files."""

from .cli import run_model_cli
from .hooks import ModelHooks

__all__ = ["ModelHooks", "run_model_cli"]
