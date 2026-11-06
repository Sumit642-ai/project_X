"""Reuse the API fixtures, plus `configure`: settings and a mocked model for the AI draft."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.ai_draft.client import get_draft_model
from app.core.config import Settings, get_settings
from tests.ai_draft.helpers import RAYMOND_DRAFT, TRANSCRIPTS, Configure, FakeModel
from tests.api.conftest import Api, api, api_template  # noqa: F401


@pytest.fixture
def configure(api: Api, tmp_path: Path) -> Iterator[Configure]:  # noqa: F811
    """configure(reply, demo_mode=True, pods=[], transcripts={member_id: text})."""

    def apply(
        reply: dict[str, Any] | str | Exception = RAYMOND_DRAFT,
        demo_mode: bool = True,
        pods: list[str] | None = None,
        transcripts: dict[str, str] | None = None,
    ) -> FakeModel:
        folder = tmp_path / "transcripts"
        folder.mkdir(parents=True, exist_ok=True)
        for path in TRANSCRIPTS.glob("*.txt"):
            (folder / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        for member_id, text in (transcripts or {}).items():
            (folder / f"{member_id}.txt").write_text(text, encoding="utf-8")
        settings = Settings(demo_mode=demo_mode, ai_draft_pods=pods or [], transcripts_dir=folder)
        model = FakeModel(reply)
        api.app.dependency_overrides[get_settings] = lambda: settings
        api.app.dependency_overrides[get_draft_model] = lambda: model
        return model

    yield apply
    api.app.dependency_overrides.pop(get_settings, None)
    api.app.dependency_overrides.pop(get_draft_model, None)
