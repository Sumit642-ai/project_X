"""Signal rules. Each rule reads a member snapshot and cites the Facts it used.

Rules only flag and suggest; they never change doses, coverage, identity or consent.
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

from app.core.clock import Clock
from app.facts.models import Fact
from app.facts.snapshot import MemberSnapshot
from app.signals.base import Rule, Signal
from app.signals.calendar import due_at
from app.signals.evidence import (
    Episode,
    condition_groups,
    d,
    dispensed,
    ed_visits,
    facts,
    fills,
    inpatient_discharges,
    latest,
    member_tz,
    num,
    open_care_gaps,
    plain,
    psych_discharges,
    successful_contact_since,
    today,
)

LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "vi": "Vietnamese",
    "ht": "Haitian Creole",
    "so": "Somali",
    "ar": "Arabic",
    "ne": "Nepali",
}
SDOH_NAMES = {"general": "HRA", "housing": "Housing screen", "caregiver_strain": "Caregiver screen"}


def _recent_hf_discharge(
    snapshot: MemberSnapshot, clock: Clock, days: int = 30
) -> tuple[Episode | None, list[Fact]]:
    groups = condition_groups(snapshot)
    if "HF" not in groups:
        return None, []
    now = today(clock)
    recent = [e for e in inpatient_discharges(snapshot) if 0 <= (now - e.day).days <= days]
    return (recent[-1] if recent else None), groups["HF"]


class HfDischarge(Rule):
    rule_id = "HF_DISCHARGE"
    severity = "info"
    deadline_kind = "member_contact"
    description = "Heart-failure discharge: transition contact due 2 business days later, 17:00."

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        discharge, hf = _recent_hf_discharge(snapshot, clock)
        if discharge is None or successful_contact_since(snapshot, discharge.day):
            return []
        tz = member_tz(snapshot)
        due_day = self.calendar.add_business_days(discharge.day, 2)
        return [
            self.signal(
                snapshot,
                inputs=[*discharge.facts, *hf[-1:]],
                insight=f"HF discharge {discharge.day}; transition contact due {due_day:%a} 17:00",
                step="Call within 2 business days: review meds, symptoms and follow-up.",
                due=due_at(due_day, tz),
                tz=tz,
                key_input=discharge.key_fact,
            )
        ]


class NoCriticalMedOnHand(Rule):
    rule_id = "NO_CRITICAL_MED_ON_HAND"
    severity = "red"
    lever = True
    description = "HF discharge and the loop diuretic ran out before discharge with no fill since."

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        discharge, hf = _recent_hf_discharge(snapshot, clock)
        if discharge is None:
            return []
        diuretic = dispensed(fills(snapshot, "loop diuretic"))
        last = latest(diuretic)
        if last is None:
            return []
        covered = d(last.value.get("covered_through"))
        refilled = [f for f in diuretic if f.event_date and f.event_date >= discharge.day]
        if covered is None or covered >= discharge.day or refilled:
            return []
        return [
            self.signal(
                snapshot,
                inputs=[last, *discharge.facts, *hf[-1:]],
                insight=f"{last.value['product']} ran out {covered}; no fill since discharge",
                step="Confirm diuretic supply and current dose with member and prescriber today.",
                key_input=discharge.key_fact,
            )
        ]


class DrugRejectedNoRequest(Rule):
    rule_id = "DRUG_REJECTED_NO_REQUEST"
    severity = "amber"
    lever = True
    description = "A claim rejected for prior authorisation with no coverage request filed."

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        now = today(clock)
        requests = facts(snapshot, "coverage", "auth:")
        signals = []
        for reject in fills(snapshot):
            v = reject.value
            if v.get("dispensed") or v.get("reject_code") != "75" or reject.event_date is None:
                continue
            if (now - reject.event_date).days > 30:
                continue
            later_fill = [
                f
                for f in dispensed(fills(snapshot))
                if f.key == reject.key and (f.event_date or now) >= reject.event_date
            ]
            product = str(v.get("product"))
            filed = [
                r
                for r in requests
                if (d(r.value.get("requested_date")) or now) >= reject.event_date
                and product.lower() in str(r.value.get("item")).lower()
            ]
            if later_fill or filed:
                continue
            signals.append(
                self.signal(
                    snapshot,
                    inputs=[reject],
                    insight=f"{product} rejected (PA required); no coverage request filed",
                    step="Ask the prescriber to file the coverage determination (expedited).",
                    key_input=reject,
                )
            )
        return signals


class DischargeSummaryMissing(Rule):
    rule_id = "DISCHARGE_SUMMARY_MISSING"
    severity = "info"
    description = "A discharge summary was requested more than 24 hours ago and has not arrived."

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        now = clock.now()
        signals = []
        for doc in snapshot.documents:
            if doc.type != "discharge_summary" or doc.status != "requested" or not doc.requested_at:
                continue
            age = now - doc.requested_at
            if not timedelta(hours=24) <= age <= timedelta(days=30):
                continue
            ids = {e["fact_id"] for e in doc.evidence if "fact_id" in e}
            inputs = [v.fact for v in snapshot.facts if v.fact.id in ids]
            if not inputs:
                continue
            requested = doc.requested_at.astimezone(ZoneInfo(member_tz(snapshot))).date()
            signals.append(
                self.signal(
                    snapshot,
                    inputs=inputs,
                    insight=f"Discharge summary requested {requested}, not received",
                    step="Re-query the HIE; ask the member for discharge papers on the call.",
                    key_input=inputs[0],
                )
            )
        return signals


class EdRepeat90d(Rule):
    rule_id = "ED_REPEAT_90D"
    severity = "amber"
    description = "Two or more ED visits in 90 days, counting ADT and claims once per visit."

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        now = today(clock)
        visits = [v for v in ed_visits(snapshot) if 0 <= (now - v.day).days <= 90]
        if len(visits) < 2:
            return []
        adt_only = sum(1 for v in visits if v.sources == {"adt"})
        insight = f"{len(visits)} ED visits in 90 days"
        if adt_only:
            insight += f"; {adt_only} only in ADT"
        return [
            self.signal(
                snapshot,
                inputs=[f for v in visits for f in v.facts],
                insight=insight,
                step="Ask what drives the ED visits; agree an action plan for flare-ups.",
                key_input=visits[-1].key_fact,
            )
        ]


class RescueMedGapAfterEd(Rule):
    rule_id = "RESCUE_MED_GAP_AFTER_ED"
    severity = "amber"
    lever = True
    description = "Recent ED visit and the rescue inhaler (SABA) ran out before it, not refilled."

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        now = today(clock)
        visits = [v for v in ed_visits(snapshot) if 0 <= (now - v.day).days <= 14]
        saba = dispensed(fills(snapshot, "SABA"))
        last = latest(saba)
        if not visits or last is None:
            return []
        visit = visits[-1]
        covered = d(last.value.get("covered_through"))
        if (
            covered is None
            or covered >= visit.day
            or any((f.event_date or now) >= visit.day for f in saba)
        ):
            return []
        return [
            self.signal(
                snapshot,
                inputs=[last, *visit.facts],
                insight=f"ED visit {visit.day}; no rescue inhaler since {covered}",
                step="Arrange a rescue inhaler refill and check the asthma action plan.",
                key_input=visit.key_fact,
            )
        ]


class FmcDue(Rule):
    rule_id = "FMC_DUE"
    severity = "info"
    deadline_kind = "member_contact"
    description = "Follow-up within 7 days of an ED visit (multiple chronic conditions)."

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        now = today(clock)
        recent = [v for v in ed_visits(snapshot) if 0 <= (now - v.day).days <= 7]
        gaps = open_care_gaps(snapshot, "FMC")
        groups = condition_groups(snapshot)
        if not recent or (not gaps and len(groups) < 2):
            return []
        visit = recent[-1]
        tz = member_tz(snapshot)
        due_day = visit.day + timedelta(days=7)
        return [
            self.signal(
                snapshot,
                inputs=[*visit.facts, *gaps],
                insight=f"ED follow-up visit due by {due_day}",
                step="Book a primary-care or specialist visit within 7 days of the ED visit.",
                due=due_at(due_day, tz),
                tz=tz,
                key_input=visit.key_fact,
            )
        ]


class PsychDischargeNoContact(Rule):
    rule_id = "PSYCH_DISCHARGE_NO_CONTACT"
    severity = "red"
    lever = True
    description = "Psychiatric discharge in the last 7 days with no successful contact since."

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        now = today(clock)
        recent = [e for e in psych_discharges(snapshot) if 0 <= (now - e.day).days <= 7]
        if not recent or successful_contact_since(snapshot, recent[-1].day):
            return []
        discharge = recent[-1]
        return [
            self.signal(
                snapshot,
                inputs=discharge.facts,
                insight=f"Psychiatric discharge {discharge.day}; no successful contact since",
                step="Reach the member today through an authorised contact; confirm follow-up.",
                key_input=discharge.key_fact,
            )
        ]


class FuhDue(Rule):
    rule_id = "FUH_DUE"
    severity = "info"
    deadline_kind = "member_contact"
    description = "Behavioural-health follow-up within 7 days of a psychiatric discharge."

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        now = today(clock)
        recent = [e for e in psych_discharges(snapshot) if 0 <= (now - e.day).days <= 7]
        if not recent:
            return []
        discharge = recent[-1]
        tz = member_tz(snapshot)
        due_day = discharge.day + timedelta(days=7)
        return [
            self.signal(
                snapshot,
                inputs=discharge.facts,
                insight=f"Behavioral health follow-up due by {due_day}",
                step="Confirm a behavioural-health appointment within 7 days of discharge.",
                due=due_at(due_day, tz),
                tz=tz,
                key_input=discharge.key_fact,
            )
        ]


class LtssHoursCut(Rule):
    rule_id = "LTSS_HOURS_CUT"
    severity = "amber"
    lever = True
    deadline_kind = "appeal"
    description = "Medicaid LTSS aide hours reduced at reassessment; appeal window open."

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        now = today(clock)
        signals = []
        for fact in facts(snapshot, "service"):
            v = fact.value
            prior, current = (
                num(v.get("prior_hours_per_week")),
                num(v.get("authorized_hours_per_week")),
            )
            if prior is None or current is None or current >= prior:
                continue
            notice, window = d(v.get("notice_date")), v.get("appeal_window_days")
            appeal_by = notice + timedelta(days=int(window)) if notice and window else None
            if appeal_by is not None and appeal_by < now:
                continue
            change = round((current - prior) / prior * 100)
            insight = f"Aide hours cut {plain(prior)} to {plain(current)} ({change}%)"
            tz = member_tz(snapshot)
            if appeal_by:
                insight += f"; appeal by {appeal_by}"
            signals.append(
                self.signal(
                    snapshot,
                    inputs=[fact],
                    insight=insight,
                    step="Discuss the reduction with member and caregiver; offer appeal support.",
                    due=due_at(appeal_by, tz) if appeal_by else None,
                    tz=tz,
                    key_input=fact,
                )
            )
        return signals


class DmeAuthOverdue(Rule):
    rule_id = "DME_AUTH_OVERDUE"
    severity = "amber"
    deadline_kind = "um"  # UM-owned: shown, never scored as a member-contact deadline
    description = "A pending authorisation is past its decision date."

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        now = today(clock)
        signals = []
        for fact in facts(snapshot, "coverage", "auth:"):
            v = fact.value
            due = d(v.get("decision_due"))
            if v.get("status") != "pending" or due is None or due >= now:
                continue
            tz = member_tz(snapshot)
            signals.append(
                self.signal(
                    snapshot,
                    inputs=[fact],
                    insight=f"{v.get('item')} authorisation overdue since {due}",
                    step=f"Escalate to UM; missing: {v.get('missing_documents') or 'UNKNOWN'}.",
                    due=due_at(due, tz),
                    tz=tz,
                    key_input=fact,
                )
            )
        return signals


class CaregiverStrain(Rule):
    rule_id = "CAREGIVER_STRAIN"
    severity = "amber"
    lever = True
    description = "High caregiver burden on the latest caregiver-strain screen."

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        screen = latest(facts(snapshot, "sdoh", "caregiver_strain"))
        if screen is None:
            return []
        v = screen.value
        score, top = v.get("score"), v.get("score_max")
        high = v.get("risk_level") == "high" or (
            score is not None and top and int(score) / int(top) >= 0.625
        )
        if not high:
            return []
        return [
            self.signal(
                snapshot,
                inputs=[screen],
                insight=f"Caregiver strain high: {score} of {top}",
                step="Ask the caregiver about respite, aide hours and support services.",
                key_input=screen,
            )
        ]


class NonformularyNeverFilled(Rule):
    rule_id = "NONFORMULARY_NEVER_FILLED"
    severity = "info"
    lever = True
    description = "Rejected as non-formulary and nothing in the same class filled since."

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        now = today(clock)
        signals = []
        for reject in fills(snapshot):
            v = reject.value
            if v.get("dispensed") or v.get("reject_code") != "70" or reject.event_date is None:
                continue
            if (now - reject.event_date).days > 180:
                continue
            alternative = [
                f
                for f in dispensed(fills(snapshot, v.get("drug_class")))
                if (f.event_date or now) >= reject.event_date
            ]
            if alternative:
                continue
            signals.append(
                self.signal(
                    snapshot,
                    inputs=[reject],
                    insight=f"{v.get('product')} rejected as non-formulary; never filled",
                    step="Ask the prescriber about the formulary alternative or an exception.",
                    key_input=reject,
                )
            )
        return signals


class LanguageMismatchOutreach(Rule):
    rule_id = "LANGUAGE_MISMATCH_OUTREACH"
    severity = "info"
    description = "Two or more recent calls in a language the contact does not prefer."

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        preference = latest(facts(snapshot, "preference", "language"))
        if preference is None:
            return []
        target = preference.value.get("proxy_language") or preference.value.get(
            "preferred_language"
        )
        if not target:
            return []
        now = clock.now()
        calls = [
            f
            for f in facts(snapshot, "event", "outreach:call")
            if f.value.get("language_used") not in (None, target)
            and f.event_date
            and (now.date() - f.event_date).days <= 60
        ]
        if len(calls) < 2:
            return []
        used = LANGUAGE_NAMES.get(
            calls[-1].value["language_used"], calls[-1].value["language_used"]
        )
        wanted = LANGUAGE_NAMES.get(target, target)
        return [
            self.signal(
                snapshot,
                inputs=[preference, *calls],
                insight=f"{len(calls)} {used} calls to a {wanted} speaker",
                step=f"Route to a {wanted}-speaking case manager or use an interpreter.",
                key_input=calls[-1],
            )
        ]


class StaleSdoh(Rule):
    rule_id = "STALE_SDOH"
    severity = "info"
    description = "The latest screen in an SDOH domain is more than 180 days old."

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        now = today(clock)
        by_domain: dict[str, list[Fact]] = {}
        for fact in facts(snapshot, "sdoh"):
            by_domain.setdefault(fact.key, []).append(fact)
        signals = []
        for domain, screens in sorted(by_domain.items()):
            screen = latest(screens)
            if screen is None or screen.event_date is None:
                continue
            age = (now - screen.event_date).days
            if age > 180:
                signals.append(
                    self.signal(
                        snapshot,
                        inputs=[screen],
                        insight=f"{SDOH_NAMES.get(domain, domain)} {age} days old",
                        step="Re-screen on the next call.",
                        key_input=screen,
                    )
                )
        return signals


class ContactDisconnected(Rule):
    rule_id = "CONTACT_DISCONNECTED"
    severity = "info"
    description = "A number on the contact ladder is disconnected."

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        by_id = {v.fact.id: v.fact for v in snapshot.facts}
        alternatives = [c for c in snapshot.contacts if c.callable and c.owner == "self"]
        signals = []
        for contact in snapshot.contacts:
            if contact.last_outcome != "disconnected":
                continue
            inputs = [by_id[i] for i in contact.fact_ids if i in by_id]
            if not inputs:
                continue
            insight = f"Number {contact.number} disconnected"
            if alternatives:
                insight += f"; newer {alternatives[0].number} available"
            signals.append(
                self.signal(
                    snapshot,
                    inputs=inputs,
                    insight=insight,
                    step="Use the next number on the ladder; update the contact record.",
                    key_input=inputs[0],
                )
            )
        return signals


ESCALATE_CLASSES = ("loop diuretic", "basal insulin")
REFILL_GRACE_DAYS = 7
REFILL_LOOKBACK_DAYS = 90


class ExpectedRefillMissing(Rule):
    rule_id = "EXPECTED_REFILL_MISSING"
    severity = "info"  # amber for loop diuretics, insulin, or a rescue inhaler after an ED visit
    lever = True
    description = (
        "Silence detection: a maintenance medicine's supply ended over 7 days ago with no new "
        "fill and no reject on file."
    )

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        now = today(clock)
        all_fills = fills(snapshot)
        recent_ed = [v for v in ed_visits(snapshot) if 0 <= (now - v.day).days <= 14]
        by_drug: dict[str, list[Fact]] = {}
        for fill in dispensed(all_fills):
            by_drug.setdefault(fill.key, []).append(fill)
        signals = []
        for key, drug_fills in sorted(by_drug.items()):
            last = latest(drug_fills)
            covered = d(last.value.get("covered_through")) if last else None
            if last is None or last.event_date is None or covered is None:
                continue
            overdue = (now - covered).days
            if not REFILL_GRACE_DAYS < overdue <= REFILL_LOOKBACK_DAYS:
                continue
            rejected = [
                f
                for f in all_fills
                if f.key == key
                and not f.value.get("dispensed")
                and (f.event_date or now) >= last.event_date
            ]
            if rejected:
                continue  # a reject explains the gap; other rules handle it
            drug_class = last.value.get("drug_class")
            rescue_after_ed = drug_class == "SABA" and bool(recent_ed)
            escalate = drug_class in ESCALATE_CLASSES or rescue_after_ed
            inputs = [last]
            if rescue_after_ed:
                inputs += [f for v in recent_ed for f in v.facts]
            signals.append(
                self.signal(
                    snapshot,
                    inputs=inputs,
                    insight=f"{last.value.get('product')} refill expected {covered}; none since",
                    step="Ask if the member still takes it and has supply; check for barriers.",
                    key_input=last,
                    severity="amber" if escalate else "info",
                )
            )
        return signals


RULES: tuple[type[Rule], ...] = (
    HfDischarge,
    NoCriticalMedOnHand,
    DrugRejectedNoRequest,
    DischargeSummaryMissing,
    EdRepeat90d,
    RescueMedGapAfterEd,
    FmcDue,
    PsychDischargeNoContact,
    FuhDue,
    LtssHoursCut,
    DmeAuthOverdue,
    CaregiverStrain,
    NonformularyNeverFilled,
    LanguageMismatchOutreach,
    StaleSdoh,
    ContactDisconnected,
    ExpectedRefillMissing,
)
RULES_BY_ID = {rule.rule_id: rule for rule in RULES}
