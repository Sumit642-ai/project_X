"""Vercel entry point for the one-project deploy (Root Directory: the repository root).

The frontend is served as static files; /api/* is rewritten here (see vercel.json)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from vercel_app import app  # noqa: E402

__all__ = ["app"]
