"""Security: CORS, sign-in rate limit, token expiry, secrets, and PHI-free logs."""

import logging
import os
import re
from pathlib import Path

import pytest

from app.api.ratelimit import SlidingWindowLimiter
from app.core.config import REPO_ROOT, get_settings
from app.core.logging import JsonFormatter, mask
from tests.api.conftest import Api, api, api_template  # noqa: F401  (API fixtures)

FRONTEND = "http://localhost:5173"


# --- CORS -------------------------------------------------------------------------------------


def test_cors_allows_only_the_frontend_origin(api: Api) -> None:
    preflight = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"}
    ok = api.client.options("/queue", headers={"Origin": FRONTEND, **preflight})
    assert ok.headers.get("access-control-allow-origin") == FRONTEND
    evil = api.client.options("/queue", headers={"Origin": "https://evil.example", **preflight})
    assert "access-control-allow-origin" not in evil.headers
    simple = api.client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in simple.headers


def test_cors_origins_come_from_settings() -> None:
    assert get_settings().cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]


# --- sign-in rate limit -----------------------------------------------------------------------


def test_sign_in_is_rate_limited_per_client(api: Api) -> None:
    limit = get_settings().login_rate_limit
    for _ in range(limit):
        assert api.client.post("/auth/login", json={"username": "maria"}).status_code == 200
    blocked = api.client.post("/auth/login", json={"username": "maria"})
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) >= 1
    unknown = api.client.post("/auth/login", json={"username": "mallory"})
    assert unknown.status_code == 429  # guessing usernames counts too


def test_the_window_slides() -> None:
    now = [0.0]
    limiter = SlidingWindowLimiter(2, 60, now=lambda: now[0])
    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")
    with pytest.raises(Exception, match="429"):
        limiter.check("1.2.3.4")
    limiter.check("5.6.7.8")  # another client is unaffected
    now[0] = 60.0
    limiter.check("1.2.3.4")  # the oldest attempt left the window


# --- secrets ----------------------------------------------------------------------------------

SECRET_PATTERNS = {
    "Anthropic API key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36}"),
    "Slack token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    "password assignment": re.compile(r"(?i)\b(password|passwd|secret)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"),
}
SKIP_DIRS = {".venv", "node_modules", ".git", "__pycache__", ".mypy_cache", ".ruff_cache",
             ".pytest_cache", "dist", "test-results", "playwright-report", ".data", "landing",
             "screenshots", "demo"}  # fmt: skip
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".yaml", ".yml", ".toml",
                 ".md", ".txt", ".csv", ".hl7", ".xml", ".ini", ".cfg", ".example", ".html"}  # fmt: skip


def _repo_files() -> list[Path]:
    """Source files, pruning dependency and build directories while walking."""
    files = []
    for folder, dirs, names in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            path = Path(folder) / name
            if path.suffix in TEXT_SUFFIXES or name.startswith(".env"):
                files.append(path)
    return files


def test_no_secrets_in_the_repository() -> None:
    findings = []
    for path in _repo_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(REPO_ROOT)}: {label}")
    assert findings == [], findings
    assert not (REPO_ROOT / ".env").exists() or "sk-ant-" not in (REPO_ROOT / ".env").read_text()


def test_only_the_example_env_file_is_kept() -> None:
    env_files = sorted(p.name for p in REPO_ROOT.glob(".env*"))
    assert env_files in (
        [".env.example"],
        [".env", ".env.example"],  # a developer's local copy (git-ignored)
    )
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert re.search(r"(?m)^\.env$", gitignore)


# --- PHI-free logs ----------------------------------------------------------------------------

PHI = re.compile(r"Raymond|Tull|Joan|Kayla|Morrison|555-01\d\d|joan@example\.com")


def test_masking_removes_phones_emails_and_member_names() -> None:
    from app.core.logging import register_names

    register_names(["Raymond", "Tull"])
    assert mask("Call Raymond Tull at 555-0142 or (216) 555-0143, joan@example.com") == (
        "Call [name] [name] at [phone] or [phone], [email]"
    )
    assert mask("load 12 of 99001-0002-30 at 2026-11-09T08:00") == (
        "load 12 of 99001-0002-30 at 2026-11-09T08:00"
    )  # NDCs and timestamps survive


def test_log_lines_never_contain_names_or_phone_numbers(
    api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    maria = api.as_("maria")
    caplog.set_level(logging.DEBUG)
    api.client.get("/members/search?q=Raymond Tull", headers=maria)
    api.client.get("/members/search?q=555-0142", headers=maria)
    api.client.get("/members/SYN-001/360", headers=maria)
    api.client.post("/inbound-call", json={"from_number": "555-0143"}, headers=maria)
    logging.getLogger("casecompass.test").warning(
        "Joan called back about Raymond on 555-0143 (joan@example.com)"
    )
    logging.getLogger("casecompass.test").info("x", extra={"phone": "555-0142", "full_name": "Kayla Morrison"})

    lines = [JsonFormatter().format(r) for r in caplog.records]
    assert any('"route": "/members/search"' in line for line in lines)  # requests are logged
    assert any('"member_id": "SYN-001"' in line for line in lines)  # ids, not names
    leaks = [line for line in lines if PHI.search(line)]
    assert leaks == []


def test_request_logs_are_structured_json(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    import json

    caplog.set_level(logging.INFO, logger="casecompass.request")
    api.client.get("/health")
    record = next(r for r in caplog.records if r.name == "casecompass.request")
    entry = json.loads(JsonFormatter().format(record))
    assert {"ts", "level", "logger", "msg", "method", "route", "status", "duration_ms"} <= set(entry)
    assert (entry["route"], entry["status"]) == ("/health", 200)
