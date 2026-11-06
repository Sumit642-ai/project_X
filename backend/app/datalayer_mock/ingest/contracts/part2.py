from datetime import date

from app.datalayer_mock.ingest.contracts.base import Contract, StreamContract, SynId


class Part2NoteRow(Contract):
    """42 CFR Part 2 program records. Staged as received; masking happens at read time."""

    note_id: SynId
    member_id: SynId
    program_name: str
    service_date: date
    note_type: str
    counselor: str | None
    note_text: str
    redisclosure_prohibited: bool


CONTRACTS = (StreamContract("part2", "new_dawn_notes", "csv", Part2NoteRow, "stg_part2_notes"),)
