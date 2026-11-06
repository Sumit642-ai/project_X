"""Assessment template: 40 fields in six groups, prefilled from Facts.

No external blueprint was available, so this list is CaseCompass's own: a field is prefillable
only if some feed can supply it. Status rules:
  prefilled_fresh  source as-of within 180 days: the nurse confirms it
  prefilled_stale  source older than 180 days, or no source on file: the nurse re-asks
  live_only        always asked live
Medication, allergy and dose fields are high-risk: confirmed one by one, never in bulk.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.consent import policy
from app.core.clock import PLAN_TZ, Clock
from app.facts.models import ContactPoint, Fact
from app.facts.snapshot import MemberSnapshot

STALE_AFTER = timedelta(days=180)


@dataclass(frozen=True)
class Prefill:
    value: Any
    facts: list[Fact]
    as_of: date | None


Resolver = Callable[[MemberSnapshot], Prefill | None]


@dataclass(frozen=True)
class FieldDef:
    field_id: str
    group: str
    label: str
    risk: str = "low"
    resolver: Resolver | None = None  # None = live only


# --- helpers ----------------------------------------------------------------------------------


def _facts(s: MemberSnapshot, fact_type: str, prefix: str = "") -> list[Fact]:
    return [
        v.fact
        for v in s.facts
        if not v.masked and v.fact.type == fact_type and v.fact.key.startswith(prefix)
    ]


def _latest(items: list[Fact]) -> Fact | None:
    return max(items, key=lambda f: (f.event_date or date.min, f.id), default=None)


def _loaded(f: Fact) -> date:
    return f.loaded_at.astimezone(PLAN_TZ).date()


def _coverage(s: MemberSnapshot) -> Fact | None:
    return _latest(_facts(s, "coverage", "plan:"))


def _best_contact(s: MemberSnapshot) -> ContactPoint | None:
    callable_ = policy.callable_contacts(s.contacts)
    return max(callable_, key=lambda c: (c.confidence, c.number), default=None)


def _contact_facts(s: MemberSnapshot, contact: ContactPoint) -> list[Fact]:
    ids = set(contact.fact_ids)
    return [v.fact for v in s.facts if v.fact.id in ids]


def _meds(s: MemberSnapshot, classes: tuple[str, ...]) -> Prefill | None:
    items = [f for f in _facts(s, "medication") if f.value.get("drug_class") in classes]
    if not items:
        return None
    value = [
        {
            "source": f.source_system,
            "product": f.value.get("product"),
            "strength": f.value.get("strength"),
            "date": str(f.event_date),
        }
        for f in sorted(items, key=lambda f: (f.event_date or date.min, f.id))
    ]
    return Prefill(value, items, max((f.event_date for f in items if f.event_date), default=None))


# --- resolvers --------------------------------------------------------------------------------


def name(s: MemberSnapshot) -> Prefill | None:
    cov = _coverage(s)
    return (
        Prefill(f"{s.member.first_name} {s.member.last_name}", [cov], _loaded(cov)) if cov else None
    )


def dob(s: MemberSnapshot) -> Prefill | None:
    cov = _coverage(s)
    return Prefill(str(s.member.dob), [cov], _loaded(cov)) if cov else None


def language(s: MemberSnapshot) -> Prefill | None:
    pref = _latest(_facts(s, "preference", "language"))
    if pref is None or not pref.value.get("preferred_language"):
        return None
    value = {"member": pref.value["preferred_language"], "proxy": pref.value.get("proxy_language")}
    return Prefill(value, [pref], pref.event_date or _loaded(pref))


def best_phone(s: MemberSnapshot) -> Prefill | None:
    best = _best_contact(s)
    if best is None:
        return None
    return Prefill(
        {"number": best.number, "owner": best.owner_name},
        _contact_facts(s, best),
        best.last_verified,
    )


def best_time(s: MemberSnapshot) -> Prefill | None:
    best = _best_contact(s)
    if best is None or not best.best_window:
        return None
    return Prefill(best.best_window, _contact_facts(s, best), best.last_verified)


def address(s: MemberSnapshot) -> Prefill | None:
    fact = _latest(_facts(s, "contact_point", "address"))
    if fact is None:
        return None
    v = fact.value
    return Prefill(
        f"{v.get('address_line1')}, {v.get('city')} {v.get('zip')}", [fact], fact.event_date
    )


def representative(s: MemberSnapshot) -> Prefill | None:
    reps = [
        f for f in _facts(s, "consent", "personal_representative") if f.source_system == "consents"
    ]
    fact = _latest(reps)
    if fact is None:
        return None
    v = fact.value
    return Prefill(
        {
            "name": v.get("representative_name"),
            "relationship": v.get("relationship"),
            "form_expires": v.get("expires_date"),
        },
        [fact],
        fact.event_date,
    )


def pcp(s: MemberSnapshot) -> Prefill | None:
    cov = _coverage(s)
    if cov is None or not cov.value.get("pcp"):
        return None
    return Prefill(cov.value["pcp"], [cov], _loaded(cov))


def last_admission(s: MemberSnapshot) -> Prefill | None:
    fact = _latest(
        [f for f in _facts(s, "event", "adt:admission") if f.value.get("patient_class") == "I"]
    )
    if fact is None:
        return None
    return Prefill(
        {"date": str(fact.event_date), "facility": fact.value.get("facility")},
        [fact],
        fact.event_date,
    )


def last_discharge(s: MemberSnapshot) -> Prefill | None:
    adt = [f for f in _facts(s, "event", "adt:discharge") if f.value.get("patient_class") == "I"]
    gaps = [f for f in _facts(s, "care_gap") if f.key == "TRC"]
    fact = _latest(adt) or _latest(gaps)
    if fact is None:
        return None
    return Prefill(
        {"date": str(fact.event_date), "disposition": fact.value.get("discharge_disposition")},
        [fact],
        fact.event_date,
    )


def discharge_summary(s: MemberSnapshot) -> Prefill | None:
    docs = _facts(s, "event", "document:discharge_summary")
    requests = _facts(s, "event", "document_request:discharge_summary")
    fact = _latest(docs) or _latest(requests)
    if fact is None:
        return None
    status = "received" if fact in docs else fact.value.get("status", "requested")
    return Prefill({"status": status}, [fact], fact.event_date)


def last_pcp_visit(s: MemberSnapshot) -> Prefill | None:
    fact = _latest(_facts(s, "event", "claim:office"))
    return Prefill(str(fact.event_date), [fact], fact.event_date) if fact else None


def discharge_med_list(s: MemberSnapshot) -> Prefill | None:
    items = [
        f for f in _facts(s, "medication") if f.value.get("source_kind") == "hospital_document"
    ]
    if not items:
        return None
    return Prefill(
        [f"{f.value.get('product')} {f.value.get('strength')}" for f in items],
        items,
        max((f.event_date for f in items if f.event_date), default=None),
    )


def supply_on_hand(s: MemberSnapshot) -> Prefill | None:
    fills = [
        f
        for f in _facts(s, "medication")
        if f.value.get("source_kind") == "pharmacy_claim" and f.value.get("dispensed")
    ]
    latest_by_drug: dict[str, Fact] = {}
    for fill in fills:
        if fill.key not in latest_by_drug or (fill.event_date or date.min) > (
            latest_by_drug[fill.key].event_date or date.min
        ):
            latest_by_drug[fill.key] = fill
    if not latest_by_drug:
        return None
    items = list(latest_by_drug.values())
    return Prefill(
        {k: f.value.get("covered_through") for k, f in sorted(latest_by_drug.items())},
        items,
        max((f.event_date for f in items if f.event_date), default=None),
    )


def pharmacy(s: MemberSnapshot) -> Prefill | None:
    fill = _latest(
        [f for f in _facts(s, "medication") if f.value.get("source_kind") == "pharmacy_claim"]
    )
    return Prefill(fill.value.get("pharmacy"), [fill], fill.event_date) if fill else None


def _diagnoses(s: MemberSnapshot) -> dict[str, list[Fact]]:
    groups: dict[str, list[Fact]] = {}
    for fact in _facts(s, "diagnosis"):
        if fact.value.get("condition_group"):
            groups.setdefault(fact.value["condition_group"], []).append(fact)
    return groups


def primary_condition(s: MemberSnapshot) -> Prefill | None:
    groups = _diagnoses(s)
    if not groups:
        return None
    group, items = max(groups.items(), key=lambda kv: (len(kv[1]), kv[0]))
    return Prefill(group, items, max((f.event_date for f in items if f.event_date), default=None))


def other_conditions(s: MemberSnapshot) -> Prefill | None:
    groups = _diagnoses(s)
    if len(groups) < 2:
        return None
    primary = max(groups.items(), key=lambda kv: (len(kv[1]), kv[0]))[0]
    items = [f for g, fs in groups.items() if g != primary for f in fs]
    return Prefill(
        sorted(g for g in groups if g != primary),
        items,
        max((f.event_date for f in items if f.event_date), default=None),
    )


def key_lab(s: MemberSnapshot) -> Prefill | None:
    fact = _latest(_facts(s, "lab"))
    if fact is None:
        return None
    return Prefill(
        {
            "test": fact.value.get("test_name"),
            "value": fact.value.get("value"),
            "unit": fact.value.get("unit"),
        },
        [fact],
        fact.event_date,
    )


def open_gaps(s: MemberSnapshot) -> Prefill | None:
    gaps = [f for f in _facts(s, "care_gap") if f.value.get("status") == "open"]
    if not gaps:
        return None
    return Prefill(
        [f"{f.key} due {f.value.get('due_date')}" for f in gaps],
        gaps,
        max((f.event_date for f in gaps if f.event_date), default=None),
    )


def _screen(domain: str) -> Resolver:
    def resolve(s: MemberSnapshot) -> Prefill | None:
        fact = _latest(_facts(s, "sdoh", domain))
        return Prefill(fact.value.get("result"), [fact], fact.event_date) if fact else None

    return resolve


def _representative_contact(s: MemberSnapshot) -> ContactPoint | None:
    reps = [c for c in policy.authorised_contacts(s.contacts) if c.owner == "representative"]
    return max(reps, key=lambda c: (c.confidence, c.number), default=None)


def caregiver(s: MemberSnapshot) -> Prefill | None:
    rep = _representative_contact(s)
    if rep is None:
        return None
    return Prefill(
        {"name": rep.owner_name, "relationship": rep.relationship},
        _contact_facts(s, rep),
        rep.last_verified,
    )


def medication_management(s: MemberSnapshot) -> Prefill | None:
    rep = _representative_contact(s)
    if rep is None or "pill" not in (rep.relationship or "").lower():
        return None
    return Prefill(f"{rep.owner_name} manages medicines", _contact_facts(s, rep), rep.last_verified)


def transportation(s: MemberSnapshot) -> Prefill | None:
    trips = _facts(s, "service", "nemt")
    fact = _latest(trips)
    return (
        Prefill({"nemt_last_trip": fact.value.get("status")}, [fact], fact.event_date)
        if fact
        else None
    )


FIELDS: tuple[FieldDef, ...] = (
    # Demographics and contacts (8)
    FieldDef("full_name", "demographics_contacts", "Full name", resolver=name),
    FieldDef("date_of_birth", "demographics_contacts", "Date of birth", resolver=dob),
    FieldDef(
        "preferred_language", "demographics_contacts", "Preferred language", resolver=language
    ),
    FieldDef("best_phone", "demographics_contacts", "Best phone number", resolver=best_phone),
    FieldDef("home_address", "demographics_contacts", "Home address", resolver=address),
    FieldDef("best_time", "demographics_contacts", "Best time to call", resolver=best_time),
    FieldDef(
        "representative",
        "demographics_contacts",
        "Authorised representative",
        resolver=representative,
    ),
    FieldDef("pcp", "demographics_contacts", "Primary care provider", resolver=pcp),
    # Recent events (4)
    FieldDef("last_admission", "recent_events", "Most recent admission", resolver=last_admission),
    FieldDef("last_discharge", "recent_events", "Most recent discharge", resolver=last_discharge),
    FieldDef(
        "discharge_summary", "recent_events", "Discharge summary status", resolver=discharge_summary
    ),
    FieldDef("last_pcp_visit", "recent_events", "Last PCP visit", resolver=last_pcp_visit),
    # Medications (6): all high-risk
    FieldDef(
        "loop_diuretic",
        "medications",
        "Loop diuretic and dose",
        "high",
        lambda s: _meds(s, ("loop diuretic",)),
    ),
    FieldDef(
        "hf_therapy",
        "medications",
        "Heart-failure therapy (ARNI / ACE / ARB) and dose",
        "high",
        lambda s: _meds(s, ("ARNI", "ACE inhibitor", "ARB")),
    ),
    FieldDef(
        "beta_blocker",
        "medications",
        "Beta blocker and dose",
        "high",
        lambda s: _meds(s, ("beta blocker",)),
    ),
    FieldDef(
        "discharge_med_list", "medications", "Discharge medication list", "high", discharge_med_list
    ),
    FieldDef(
        "supply_on_hand", "medications", "Supply on hand (covered through)", "high", supply_on_hand
    ),
    FieldDef("pharmacy", "medications", "Pharmacy", "high", pharmacy),
    # Conditions (4)
    FieldDef("primary_condition", "conditions", "Primary condition", resolver=primary_condition),
    FieldDef("other_conditions", "conditions", "Other conditions", resolver=other_conditions),
    FieldDef("key_lab", "conditions", "Most recent key lab", resolver=key_lab),
    FieldDef("open_care_gaps", "conditions", "Open care gaps", resolver=open_gaps),
    # Social, caregiver, ADLs (8)
    FieldDef(
        "living_situation", "social_caregiver_adls", "Living situation", resolver=_screen("general")
    ),
    FieldDef("primary_caregiver", "social_caregiver_adls", "Primary caregiver", resolver=caregiver),
    FieldDef(
        "adl_independence", "social_caregiver_adls", "ADL independence", resolver=_screen("general")
    ),
    FieldDef(
        "medication_management",
        "social_caregiver_adls",
        "Who manages medicines",
        resolver=medication_management,
    ),
    FieldDef("transportation", "social_caregiver_adls", "Transportation", resolver=transportation),
    FieldDef(
        "housing_stability",
        "social_caregiver_adls",
        "Housing stability",
        resolver=_screen("housing"),
    ),
    FieldDef("food_security", "social_caregiver_adls", "Food security"),  # no feed yet
    FieldDef(
        "caregiver_strain",
        "social_caregiver_adls",
        "Caregiver strain",
        resolver=_screen("caregiver_strain"),
    ),
    # Live only (10)
    FieldDef("allergies", "live_only", "Allergies", "high"),
    FieldDef("symptoms_today", "live_only", "Symptoms today (breathing, swelling)"),
    FieldDef("weight_today", "live_only", "Weight today"),
    FieldDef("doses_taken", "live_only", "Doses taken since discharge", "high"),
    FieldDef("falls", "live_only", "Falls since discharge"),
    FieldDef("follow_up_booked", "live_only", "Follow-up appointment booked"),
    FieldDef("ride_needed", "live_only", "Ride needed for follow-up"),
    FieldDef("teach_back", "live_only", "Teach-back of warning signs"),
    FieldDef("member_goal", "live_only", "Member's own goal"),
    FieldDef("other_concerns", "live_only", "Other concerns"),
)
FIELD_BY_ID = {f.field_id: f for f in FIELDS}
# Prefillable fields with no resolver (no feed) are re-asked like stale ones.
_NO_FEED = {"food_security"}


@dataclass(frozen=True)
class FieldState:
    definition: FieldDef
    status: str
    reason: str | None
    prefill: Prefill | None


def evaluate_template(snapshot: MemberSnapshot, clock: Clock) -> list[FieldState]:
    today = clock.now().astimezone(PLAN_TZ).date()
    states = []
    for field in FIELDS:
        if field.group == "live_only":
            states.append(FieldState(field, "live_only", "always asked live", None))
            continue
        prefill = field.resolver(snapshot) if field.resolver else None
        if prefill is None:
            why = "no feed supplies this yet" if field.field_id in _NO_FEED else "no source on file"
            states.append(FieldState(field, "prefilled_stale", f"{why}: ask", None))
        elif prefill.as_of is None or today - prefill.as_of > STALE_AFTER:
            states.append(
                FieldState(
                    field,
                    "prefilled_stale",
                    f"source older than 180 days (as of {prefill.as_of}): re-ask",
                    prefill,
                )
            )
        else:
            states.append(
                FieldState(field, "prefilled_fresh", f"source as of {prefill.as_of}", prefill)
            )
    return states
