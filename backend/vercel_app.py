"""CaseCompass on Vercel (serverless Python): the whole backend as one ASGI app.

Vercel functions have a read-only file system except /tmp and no second server, so on a cold
start this module:
- copies the prebuilt demo bundle (deploy/demo-data: SQLite database, synthetic feed files,
  demo state) to /tmp, which the demo needs writable for resets and clock steps;
- runs the mock CM platform inside the same process (MOCK_CM_URL=inprocess);
- turns demo mode on with the clock frozen at the reference instant.

Every default can be overridden with a Vercel environment variable (set JWT_SECRET there).
Requests may arrive as /api/health (one project serving frontend and API) or /health (a
separate backend project): the /api prefix is optional.

Synthetic data only. State lives in /tmp, per function instance: a cold start is a fresh demo.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BUNDLE = HERE / "deploy" / "demo-data"
SEED = HERE / "deploy" / "seed"
RUNTIME = Path(
    os.environ.get("CASECOMPASS_RUNTIME_DIR", Path(tempfile.gettempdir()) / "casecompass")
)


def _prepare_runtime() -> None:
    """Copy the read-only bundle to the writable runtime directory, once per instance."""
    if (RUNTIME / "demo.db").is_file():
        return
    if not (BUNDLE / "demo.db").is_file():
        raise RuntimeError(f"demo bundle missing at {BUNDLE}: run `make vercel-bundle`")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    shutil.copytree(BUNDLE / "raw", RUNTIME / "raw", dirs_exist_ok=True)
    shutil.copyfile(BUNDLE / "demo.db", RUNTIME / "demo.db")
    shutil.copyfile(BUNDLE / "demo.db", RUNTIME / "pristine.db")
    shutil.copyfile(BUNDLE / "demo_state.json", RUNTIME / "demo_state.json")


def _defaults() -> None:
    seed = SEED if SEED.is_dir() else HERE.parent / "data" / "seed"
    for key, value in {
        "APP_ENV": "demo",
        "DEMO_MODE": "true",
        "CLOCK_MODE": "fixed",
        "DATA_DIR": str(RUNTIME),
        "DATABASE_URL": f"sqlite:///{(RUNTIME / 'demo.db').as_posix()}",
        "MOCK_CM_URL": "inprocess",
        "SEED_DIR": str(seed),
        "TRANSCRIPTS_DIR": str(seed / "transcripts"),
        "TRUST_PROXY_HEADERS": "true",
        "JWT_TTL_MINUTES": "10080",  # the demo clock jumps to Tuesday
    }.items():
        os.environ.setdefault(key, value)


_defaults()
_prepare_runtime()

from app.main import create_app  # noqa: E402  (after the environment is set)

backend = create_app()


class StripApiPrefix:
    """/api/health -> /health, so the same app serves a combined or a separate deployment."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            path: str = scope.get("path", "")
            if path == "/api" or path.startswith("/api/"):
                scope = {**scope, "path": path[4:] or "/", "raw_path": None, "root_path": ""}
        await self.inner(scope, receive, send)


app = StripApiPrefix(backend)
