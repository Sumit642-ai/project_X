"""Round-trip every mapped field: ours -> mapping -> mock CM -> mapping -> ours."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.writeback.client import CmClient
from app.writeback.mapping import FieldMap, load_mapping
from mock_cm.app import create_app as create_mock_cm

SAMPLES: dict[str, Any] = {
    "str": "Takes furosemide 40 mg",
    "bool": True,
    "date": date(2026, 11, 10),
    "datetime": datetime(2026, 11, 9, 13, 30, tzinfo=UTC),
    "json": {"number": "555-0142", "owner": "Raymond Tull", "list": ["a", "b"]},
}
ALL_FIELDS = [m for section in load_mapping().values() for m in section]


@pytest.fixture(scope="module")
def cm(tmp_path_factory: pytest.TempPathFactory) -> Iterator[CmClient]:
    path: Path = tmp_path_factory.mktemp("mock_cm") / "cm.db"
    with TestClient(create_mock_cm(f"sqlite:///{path}")) as client:
        yield CmClient(client)


def test_mapping_covers_every_assessment_field() -> None:
    from app.encounters.template import FIELDS

    mapped = {m.ours for m in load_mapping()["assessment"]}
    assert mapped == {f.field_id for f in FIELDS}
    assert len({m.theirs for m in ALL_FIELDS}) == len(ALL_FIELDS)  # no two fields collide


@pytest.mark.parametrize("field", ALL_FIELDS, ids=lambda m: f"{m.section}.{m.ours}")
def test_round_trip_through_the_cm_platform(field: FieldMap, cm: CmClient) -> None:
    value = SAMPLES[field.type]
    payload: dict[str, Any] = {"note": {}, "assessment": {}, "tasks": []}
    encoded = {field.theirs: field.encode(value)}
    if field.section == "task":
        payload["tasks"] = [encoded]
    else:
        payload[field.section] = encoded
    member = f"SYN-RT-{field.section}-{field.ours}".upper().replace("_", "-")[:40]

    version = cm.record_version(member)
    result = cm.write(member, f"rt-{field.section}-{field.ours}", payload, version)
    assert result.status == "created"
    record = cm.http.get(f"/members/{member}/record").json()

    stored = {
        "note": record["notes"][0] if record["notes"] else {},
        "assessment": record["assessment"],
        "task": record["tasks"][0] if record["tasks"] else {},
    }[field.section]
    assert field.decode(stored[field.theirs]) == value
