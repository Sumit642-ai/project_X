"""Opt-in: Raymond's transcript against the real Anthropic API. Skipped unless --live.

    cd backend && .venv/Scripts/python -m pytest tests/ai_draft/test_live.py --live

Needs ANTHROPIC_API_KEY (or an `ant auth login` profile); AI_DRAFT_MODEL picks the model.
"""

import re

import pytest

from app.ai_draft import prompt
from app.ai_draft.client import get_draft_model
from app.ai_draft.medications import known_terms
from app.ai_draft.transcript import load_transcript, render
from app.ai_draft.validate import check_draft, parse_output
from tests.ai_draft.helpers import TRANSCRIPTS

NO_SUPPLY = re.compile(r"no (furosemide )?(supply )?(at home|in the house|on hand)", re.IGNORECASE)


@pytest.mark.live
def test_raymonds_draft_cites_furosemide_and_no_supply_at_home() -> None:
    turns = load_transcript(TRANSCRIPTS, "SYN-001")
    assert turns
    facts = "furosemide metoprolol succinate sacubitril valsartan"

    reply = get_draft_model().complete(
        prompt.SYSTEM_PROMPT, prompt.user_message(turns), prompt.OUTPUT_SCHEMA
    )
    draft = check_draft(parse_output(reply.text), turns, known_terms(render(turns), facts))

    supported = [s for s in draft.sentences if s.status == "supported"]
    furosemide = [s for s in supported if "furosemide" in s.text.lower()]
    assert furosemide, [s.text for s in draft.sentences]
    no_supply = [s for s in supported if NO_SUPPLY.search(s.text)]
    assert no_supply, [s.text for s in draft.sentences]
    # Cited to the turns where Joan says there is none in the house (10) and none taken (12-13).
    assert any(set(s.source_turns) & {10, 12, 13} for s in no_supply)
    assert all(s.source_turns for s in furosemide + no_supply)
    assert draft.flagged_medications == []  # "metro-something" must not be resolved by guessing
