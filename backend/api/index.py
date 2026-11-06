"""Vercel entry point for a backend-only project (Root Directory: backend)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vercel_app import app  # noqa: E402

__all__ = ["app"]
