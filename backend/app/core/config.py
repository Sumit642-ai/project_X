from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> repo root (in the container: /app/app/core -> /).
REPO_ROOT = Path(__file__).resolve().parents[3]

# Plan-observed holidays (observed dates). Veterans Day is a business day for the plan.
DEFAULT_HOLIDAYS = (
    date(2026, 1, 1),
    date(2026, 1, 19),
    date(2026, 5, 25),
    date(2026, 7, 3),
    date(2026, 9, 7),
    date(2026, 11, 26),
    date(2026, 11, 27),
    date(2026, 12, 25),
    date(2027, 1, 1),
    date(2027, 1, 18),
    date(2027, 5, 31),
    date(2027, 7, 5),
    date(2027, 9, 6),
    date(2027, 11, 25),
    date(2027, 11, 26),
    date(2027, 12, 24),
)


class Settings(BaseSettings):
    """Application settings, read from environment variables and .env.

    .env is looked up in the working directory and its parent, so it is found both
    when running from /backend and from the repo root.
    """

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["local", "test", "demo"] = "local"
    database_url: str = "postgresql+psycopg://casecompass:change-me@localhost:5432/casecompass"
    # "fixed" pins the clock to the reference instant (tests and demo); "system" uses wall time.
    clock_mode: Literal["fixed", "system"] = "fixed"
    data_dir: Path = REPO_ROOT / "data"
    # Plan business holidays for deadline calendars (JSON list in BUSINESS_HOLIDAYS).
    business_holidays: list[date] = Field(default_factory=lambda: list(DEFAULT_HOLIDAYS))
    # Rule kill switch: rule IDs listed here are not evaluated (JSON list in DISABLED_RULES).
    disabled_rules: list[str] = Field(default_factory=list)
    # Demo-grade auth. Login is only enabled when app_env is local, test or demo.
    jwt_secret: str = Field(default="dev-only-local-placeholder-not-a-real-secret", min_length=32)
    jwt_ttl_minutes: int = 480
    # Browser origins allowed to call the API (the frontend). JSON list in CORS_ORIGINS.
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    # Sign-in attempts allowed per client address per window (then 429).
    login_rate_limit: int = 20
    login_rate_window_seconds: int = 60
    # Mock CM platform (system of record for write-back). See backend/mock_cm/.
    mock_cm_url: str = "http://localhost:8200"
    # AI note draft (Live pane). On for every pod when DEMO_MODE=true; in a pilot it is switched
    # on pod by pod (JSON list in AI_DRAFT_PODS) while the major-edit rate is watched.
    demo_mode: bool = False
    ai_draft_pods: list[str] = Field(default_factory=list)
    # Read from ANTHROPIC_API_KEY. Unset: the SDK falls back to its own credential lookup.
    anthropic_api_key: SecretStr | None = None
    ai_draft_model: str = "claude-opus-5-5"
    ai_draft_timeout_seconds: float = 20.0
    # Synthetic call transcripts standing in for the telephony transcription feed.
    transcripts_dir: Path = REPO_ROOT / "data" / "seed" / "transcripts"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def landing_dir(self) -> Path:
        return self.data_dir / "landing"

    # Demo mode (make demo sets DATA_DIR=data/demo): frozen-clock state, deliveries, reset copy.
    @property
    def demo_state_file(self) -> Path:
        return self.data_dir / "demo_state.json"

    @property
    def demo_inbox_dir(self) -> Path:
        return self.data_dir / "inbox"

    @property
    def demo_pristine_db(self) -> Path:
        return self.data_dir / "pristine.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
