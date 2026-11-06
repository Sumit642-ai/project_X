"""CLAUDE.md terminology and scope rules, checked on the source (not only in the browser).

- The user-facing name is "Next best action (suggested)"; the API field is next_best_action.
- Duplicates and conflicts are labelled "flagged by data layer", by the API and by the UI.
- backend/app/datalayer_mock/ is documented as a simulation of the HiLabs data layer.
"""

import re
from pathlib import Path

from app.api import schemas
from app.core.config import REPO_ROOT

FRONTEND = REPO_ROOT / "frontend" / "src"
DATALAYER = REPO_ROOT / "backend" / "app" / "datalayer_mock"
LABEL = "flagged by data layer"


def _ui_sources() -> list[Path]:
    return [
        p for p in FRONTEND.rglob("*.tsx") if ".test." not in p.name and "__tests__" not in p.parts
    ]


def test_next_best_action_is_always_labelled_suggested_in_the_ui() -> None:
    uses = []
    for path in _ui_sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in re.finditer(r"next best action", line, re.IGNORECASE):
                if not line.startswith(("//", "/*", " *"), len(line) - len(line.lstrip())):
                    uses.append((path.name, number, line[match.end() : match.end() + 12]))
    assert uses, "the label should appear in the UI"
    assert all(after.startswith(" (suggested)") for _, _, after in uses), uses


def test_the_api_field_is_next_best_action() -> None:
    assert "next_best_action" in schemas.QueueRow.model_fields


def test_duplicates_and_conflicts_carry_the_data_layer_label_in_the_api() -> None:
    assert schemas.PendingLinkOut.model_fields["label"].default == LABEL
    assert schemas.ConflictOut.model_fields["label"].default == LABEL


def test_duplicates_and_conflicts_carry_the_data_layer_label_in_the_ui() -> None:
    banner = (FRONTEND / "components" / "MatchBanner.tsx").read_text(encoding="utf-8")
    queue = (FRONTEND / "pages" / "QueuePage.tsx").read_text(encoding="utf-8")
    card = (FRONTEND / "components" / "ConflictCard.tsx").read_text(encoding="utf-8")
    assert "Possible duplicate · flagged by data layer" in banner
    assert "Possible duplicate · flagged by data layer" in queue
    assert "{conflict.label}" in card  # rendered from the API's label above
    for path in _ui_sources():
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"Possible duplicate[^<\n]*", text):
            assert LABEL in match.group(), f"{path.name}: {match.group()}"


def test_the_data_layer_is_documented_as_a_simulation() -> None:
    for init in [DATALAYER / "__init__.py", *DATALAYER.glob("*/__init__.py")]:
        first = init.read_text(encoding="utf-8").splitlines()[0]
        assert first.startswith('"""Simulated HiLabs data layer'), init
    claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "SIMULATE the HiLabs data layer" in claude
    architecture = (REPO_ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "simulate" in architecture.lower() and "HiLabs data layer" in architecture
