"""Scale the synthetic dataset for performance runs: clone the 45 background members until
there are `total` of them. Clones get new SYN- ids, record ids, surname variants and shifted
birth dates; phones stay inside 555-01xx (shared, as the pool has only 100 numbers). They are
assigned to case managers who are not seeded users, so seeded caseloads stay realistic.

Only used by `make perf`; `make synth` output (and its MANIFEST) is unchanged.
"""

import math
from datetime import date, timedelta
from typing import Any

from app.synth.background import COUNT, FIRST_ID
from app.synth.dataset import Dataset

BACKGROUND_IDS = frozenset(f"SYN-{FIRST_ID + i:03d}" for i in range(COUNT))
OTHER_CMS = tuple(f"Pool CM {n:02d}" for n in range(1, 41))


def _shift(value: Any, days: int) -> Any:
    if isinstance(value, date):
        return value - timedelta(days=days)
    if isinstance(value, str) and len(value) == 10 and value[4] == "-":
        return (date.fromisoformat(value) - timedelta(days=days)).isoformat()
    return value


def _clone(row: dict[str, Any], k: int) -> dict[str, Any]:
    tag = f"C{k:03d}"
    copy = dict(row)
    for key, value in row.items():
        if key == "member_id":
            copy[key] = f"SYN-{tag}-{str(value)[4:]}"
        elif key.endswith("_id") and isinstance(value, str) and value:
            copy[key] = f"{value}-{tag}"
        elif key == "last_name" and value:
            copy[key] = f"{value}-{chr(65 + k % 26)}{chr(65 + (k // 26) % 26)}"
        elif key == "dob":
            copy[key] = _shift(value, k)
        elif key == "assigned_cm":
            copy[key] = OTHER_CMS[k % len(OTHER_CMS)]
    return copy


def scale_dataset(ds: Dataset, total: int) -> int:
    """Add clones of the background members so the dataset has `total` of them."""
    copies = max(0, math.ceil(total / COUNT) - 1)
    added = 0
    for stream, rows in ds.rows.items():
        background = [r for r in rows if r.get("member_id") in BACKGROUND_IDS]
        for k in range(1, copies + 1):
            rows.extend(_clone(r, k) for r in background)
        if stream == "eligibility_834":
            added = len(background) * copies
    return added
