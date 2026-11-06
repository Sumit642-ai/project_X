"""AI-drafted text can only reach the free-text note. Enforced by the write-back mapping, so it
holds whatever the UI or any other caller does."""

import pytest
import yaml
from sqlalchemy import select

from app.ai_draft.provenance import AiDrafted
from app.writeback.mapping import (
    MAPPING_FILE,
    AiWriteForbiddenError,
    FieldMap,
    encode_section,
    load_mapping,
)
from app.writeback.models import WritebackOutbox
from tests.ai_draft.helpers import Configure, draft, live_call
from tests.api.conftest import Api
from tests.writeback.test_writeback import MEDS

ALL_FIELDS = [m for section in load_mapping().values() for m in section]
NOT_NOTE_BODY = [m for m in ALL_FIELDS if (m.section, m.ours) != ("note", "notes")]
MEDICATION_ALLERGY_DOSE = [
    m.ours for m in load_mapping()["assessment"] if m.theirs.startswith("MED_")
] + ["allergies", "doses_taken"]


def test_the_note_body_is_the_only_field_ai_text_may_reach() -> None:
    allowed = [(m.section, m.ours, m.theirs) for m in ALL_FIELDS if m.ai_allowed]
    assert allowed == [("note", "notes", "body")]
    raw = yaml.safe_load(MAPPING_FILE.read_text(encoding="utf-8"))
    flagged = [e for section in ("note", "assessment", "task") for e in raw[section] if "ai" in e]
    assert flagged == [{"ours": "notes", "theirs": "body", "ai": "allowed"}]


def test_medication_allergy_and_dose_fields_are_covered() -> None:
    assessment = {m.ours for m in load_mapping()["assessment"]}
    assert set(MEDICATION_ALLERGY_DOSE) <= assessment
    assert {"loop_diuretic", "discharge_med_list", "allergies", "doses_taken"} <= set(
        MEDICATION_ALLERGY_DOSE
    )


@pytest.mark.parametrize("field", NOT_NOTE_BODY, ids=lambda m: f"{m.section}.{m.ours}")
def test_ai_text_is_refused_by_every_other_field(field: FieldMap) -> None:
    drafted = AiDrafted("Takes furosemide 80 mg daily.")
    for value in (drafted, {"answer": drafted}, [drafted]):
        with pytest.raises(AiWriteForbiddenError) as info:
            encode_section(field.section, {field.ours: value})
        assert info.value.fields == [f"{field.section}.{field.ours}"]


@pytest.mark.parametrize("field_id", MEDICATION_ALLERGY_DOSE)
def test_a_value_traced_to_the_draft_is_refused_by_medication_fields(field_id: str) -> None:
    with pytest.raises(AiWriteForbiddenError):
        encode_section("assessment", {field_id: "plain str"}, ai_sourced={field_id})


def test_the_note_body_accepts_ai_text() -> None:
    encoded = encode_section("note", {"notes": AiDrafted("Furosemide: no supply at home.")})
    assert encoded == {"body": "Furosemide: no supply at home."}


def test_saving_drafted_text_in_a_medication_answer_is_refused_end_to_end(
    api: Api, configure: Configure
) -> None:
    """The nurse (or a buggy client) copies a drafted sentence into the loop diuretic answer:
    the save is refused and nothing reaches the CM platform."""
    configure()
    eid = live_call(api)
    sentence = next(
        s["text"] for s in draft(api, eid).json()["draft"]["sentences"] if "Furosemide" in s["text"]
    )
    maria = api.as_("maria")
    api.client.post(f"/encounters/{eid}/wrap-up", json={"notes": "Reached Raymond."}, headers=maria)
    for field_id in MEDS:
        api.client.post(
            f"/encounters/{eid}/fields/{field_id}/confirm",
            json={"time_on_field_ms": 3000}
            | ({"answer": {"note": sentence}} if field_id == "loop_diuretic" else {}),
            headers=maria,
        )

    refused = api.client.post(f"/encounters/{eid}/save", headers=maria)

    assert refused.status_code == 422
    assert "assessment.loop_diuretic" in refused.json()["detail"]["reason"]
    assert api.cm.get("/admin/entries?member_id=SYN-001").json() == []
    with api.session() as session:
        assert session.scalars(select(WritebackOutbox)).all() == []

    # Re-confirmed in the nurse's own words, the save goes through.
    api.client.post(
        f"/encounters/{eid}/fields/loop_diuretic/confirm",
        json={"time_on_field_ms": 3000, "answer": {"note": "none at home, prescriber called"}},
        headers=maria,
    )
    assert api.client.post(f"/encounters/{eid}/save", headers=maria).json()["status"] == "synced"


def test_drafted_text_in_the_free_text_note_saves(api: Api, configure: Configure) -> None:
    configure()
    eid = live_call(api)
    note = draft(api, eid).json()["draft"]["note_text"]
    maria = api.as_("maria")
    api.client.post(f"/encounters/{eid}/wrap-up", json={"notes": note}, headers=maria)
    for field_id in MEDS:
        api.client.post(
            f"/encounters/{eid}/fields/{field_id}/confirm",
            json={"time_on_field_ms": 3000},
            headers=maria,
        )
    assert api.client.post(f"/encounters/{eid}/save", headers=maria).json()["status"] == "synced"
    (entry,) = api.cm.get("/admin/entries?member_id=SYN-001").json()
    assert entry["note"]["body"] == note
