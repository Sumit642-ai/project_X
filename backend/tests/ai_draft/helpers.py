"""A mocked drafting model (no network) and helpers for live calls with a draft."""

import json
from collections.abc import Callable
from typing import Any

from app.ai_draft.client import ModelReply
from app.core.config import REPO_ROOT
from tests.api.conftest import Api

TRANSCRIPTS = REPO_ROOT / "data" / "seed" / "transcripts"

# What a well-behaved model returns for Raymond's transcript (data/seed/transcripts/SYN-001.txt).
RAYMOND_DRAFT: dict[str, Any] = {
    "summary_sentences": [
        {
            "text": "Member came home from the hospital over the weekend and reports "
            "tiredness and puffy ankles.",
            "source_turns": [5, 6],
        },
        {"text": "Caregiver (wife) reports weight up 2 lb, 182 to 184.", "source_turns": [8]},
        {
            "text": "Caregiver reports no supply at home of furosemide and none taken since "
            "Saturday.",
            "source_turns": [10, 12, 13],
        },
    ],
    "suggested_note": [
        {
            "text": "Reached member and wife Joan on speaker; identity verified.",
            "source_turns": [2, 4],
        },
        {
            "text": "Weight up 2 lb since discharge per caregiver's log.",
            "source_turns": [8],
        },
        {
            "text": "Furosemide: no supply at home; none taken since Saturday.",
            "source_turns": [10, 13],
        },
        {
            "text": "Nurse to contact Dr Lindqvist's office today about the furosemide "
            "prescription.",
            "source_turns": [20],
        },
    ],
    "open_questions": [
        'Which heart medication does the member take ("the metro-something" or "the one that '
        'starts with an S")?',
        "Member asked whether the plan will pay for the new heart pill.",
    ],
}


class FakeModel:
    """Stands in for AnthropicDraftModel: returns a canned reply or raises."""

    name = "fake-draft-model"

    def __init__(self, reply: dict[str, Any] | str | Exception) -> None:
        self.reply = reply
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> ModelReply:
        self.calls.append((system, user, schema))
        if isinstance(self.reply, Exception):
            raise self.reply
        text = self.reply if isinstance(self.reply, str) else json.dumps(self.reply)
        return ModelReply(text, self.name, "req_fake", 1200, 300)


Configure = Callable[..., FakeModel]


def live_call(api: Api, consent: bool = True) -> int:
    """Maria on a connected call with Raymond, identity verified, transcription agreed."""
    maria = api.as_("maria")
    link_id = api.client.get("/members/SYN-001/360", headers=maria).json()["pending_links"][0]["id"]
    api.client.post(f"/members/SYN-001/links/{link_id}/confirm", headers=maria)
    encounter = api.client.post(
        "/encounters", json={"member_id": "SYN-001", "number": "555-0142"}, headers=maria
    ).json()
    eid: int = encounter["id"]
    api.client.post(f"/encounters/{eid}/verify-identity", headers=maria)
    api.client.post(
        f"/encounters/{eid}/autosave",
        json={"payload": {"pane": "live", "transcription_consent": consent}},
        headers=maria,
    )
    return eid


def draft(api: Api, eid: int, user: str = "maria") -> Any:
    return api.client.post(f"/encounters/{eid}/ai-draft", headers=api.as_(user))
