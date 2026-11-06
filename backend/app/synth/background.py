"""45 background members (SYN-006..SYN-050): plausible, varied, seeded.

Each imperfection kind that applies outside the heroes is planted in exactly
ceil(10% of 45) = 5 members, chosen with the seeded RNG. I-12 (Part 2) stays with SYN-004 only
and I-16 is a file-level lag, so neither is planted per member.
"""

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.synth.catalog import (
    CLAIMS_LOADED_THROUGH,
    CONDITION_BY_KEY,
    DRUG_BY_KEY,
    FACILITIES,
    LABS,
    LOAD_DATES,
    NON_FORMULARY_BACKGROUND,
    OLDER_ADULT_CONDITIONS,
    PHARMACY_HISTORY_START,
    PLAN,
    REF_DATE,
    STATE,
    TIER_COPAY,
    YOUNGER_ADULT_CONDITIONS,
    Drug,
    ndc,
)
from app.synth.ccda_builder import CcdaDocument, Medication
from app.synth.dataset import IMPERFECTIONS, Dataset, PhonePool, at
from app.synth.hl7_builder import AdtEvent

COUNT = 45
FIRST_ID = 6
PER_KIND = math.ceil(0.10 * COUNT)
LAST_FILL = date(2026, 11, 7)

FEMALE = (
    "Alicia",
    "Bernadette",
    "Carmen",
    "Deja",
    "Elena",
    "Farah",
    "Gloria",
    "Hana",
    "Imani",
    "Joyce",
    "Keiko",
    "Lorraine",
    "Marisol",
    "Nadia",
    "Odette",
    "Priya",
    "Quinn",
    "Rosa",
    "Sahra",
    "Tamsin",
    "Ursula",
    "Valeria",
    "Wanda",
    "Yusra",
    "Zelda",
    "Linh",
    "Amina",
    "Beatriz",
    "Colette",
    "Dolores",
)
MALE = (
    "Abdi",
    "Bernard",
    "Cedric",
    "Dmitri",
    "Emeka",
    "Felipe",
    "Gordon",
    "Hassan",
    "Ivan",
    "Jerome",
    "Khalid",
    "Lionel",
    "Marcus",
    "Nabil",
    "Oscar",
    "Pradeep",
    "Rafael",
    "Samuel",
    "Thanh",
    "Ulrich",
    "Victor",
    "Walter",
    "Xavier",
    "Yosef",
    "Zachary",
    "Bishnu",
    "Curtis",
    "Desmond",
    "Ernesto",
    "Frank",
)
LAST = (
    "Abernathy",
    "Bellweather",
    "Castellanos",
    "Dunmore",
    "Ekwueme",
    "Falkner",
    "Garrow",
    "Haddix",
    "Ingersoll",
    "Jablonski",
    "Kettering",
    "Lasko",
    "Mbeki",
    "Nordqvist",
    "Okonjo",
    "Pettibone",
    "Quillen",
    "Rasmussen",
    "Sandoval",
    "Tremblay",
    "Umarov",
    "Vasquez-Lindo",
    "Whitcombe",
    "Yarborough",
    "Zielinski",
    "Adhikari",
    "Barlowe",
    "Corrigan",
    "Delacroix",
    "Ellsworth",
    "Fairbanks",
    "Gudmundson",
    "Hollis",
    "Iwasaki",
    "Juarez",
    "Kowalczyk",
    "Lindgren",
    "Merriweather",
    "Nakashima",
    "Osterman",
    "Prendergast",
    "Ravensworth",
    "Stoltz",
    "Tobias",
    "Vukovic",
)
PREVIOUS_SURNAMES = ("Hartwell", "Brennock", "Ferrante", "Osei-Mensah", "Calloway", "Duquesne")
STREETS = (
    "Maple",
    "Oak",
    "Sycamore",
    "Hickory",
    "Willow",
    "Chestnut",
    "Poplar",
    "Linden",
    "Magnolia",
    "Juniper",
    "Aspen",
    "Hawthorn",
    "Alder",
    "Spruce",
    "Buckeye",
)
SUFFIXES = (
    ("St", "Street"),
    ("Ave", "Avenue"),
    ("Rd", "Road"),
    ("Ln", "Lane"),
    ("Ct", "Court"),
    ("Dr", "Drive"),
)
CITIES = (
    ("Columbus", "43204"),
    ("Columbus", "43211"),
    ("Columbus", "43223"),
    ("Dayton", "45405"),
    ("Dayton", "45410"),
    ("Akron", "44305"),
    ("Toledo", "43605"),
    ("Springfield", "45505"),
)
PCPS = (
    "Dr R. Okafor",
    "Dr S. Brennan",
    "Dr L. Haddad",
    "Dr P. Kowalski",
    "Dr J. Esposito",
    "Riverside FQHC",
    "Northfield Family Health",
)
CMS = ("Maria", "Alma", "Devon", "Grace", "Luis")
PHARMACIES = (
    "Larch Street Pharmacy",
    "Northside Drug",
    "Riverbend Pharmacy",
    "Maple Community Pharmacy",
    "Evergreen Mail Order",
)
LANGUAGES = (("en", 70), ("es", 10), ("so", 6), ("vi", 4), ("ar", 4), ("ne", 3), (None, 3))
LOBS = (("MA-PPO", 40), ("MEDICAID", 30), ("DUAL", 15), ("DSNP", 15))
INPATIENT_FACILITIES = ("STBRIGID", "NORTHFLD", "CARDINAL")
ED_FACILITIES = ("LAKEVIEW", "NORTHFLD")
CONDITION_LABELS = {
    "htn": "Essential hypertension",
    "t2dm": "Type 2 diabetes mellitus",
    "hld": "Hyperlipidemia",
    "hf": "Chronic systolic heart failure",
    "copd": "COPD",
    "asthma": "Moderate persistent asthma",
    "ckd3": "Chronic kidney disease, stage 3",
    "depression": "Major depressive disorder",
    "hypothyroid": "Hypothyroidism",
    "afib": "Atrial fibrillation",
    "neuropathy": "Peripheral neuropathy",
    "gerd": "GERD",
}
UM_ITEMS = (
    ("prior_auth", "MRI lumbar spine", "72148"),
    ("prior_auth", "Home oxygen", "E1390"),
    ("prior_auth", "CPAP device", "E0601"),
    ("prior_auth", "Physical therapy, 12 visits", "97110"),
    ("prior_auth", "Hospital bed (DME)", "E0250"),
    ("part_d_coverage_determination", "Apixaban 5 mg quantity limit", None),
)
MISSING_DOCS = ("Face-to-face encounter note", "Prescriber attestation", "Recent clinical notes")


@dataclass
class Rep:
    name: str
    relationship: str
    phone: str
    expires: date


@dataclass
class Member:
    member_id: str
    first: str
    last: str
    sex: str
    dob: date
    lob: str
    language: str | None
    pcp: str | None
    phone: str
    phone_as_of: date | None
    street_no: int
    street: str
    suffix: tuple[str, str]
    city: str
    zip: str
    address_as_of: date
    effective: date
    cm: str
    pharmacy: str
    conditions: list[str]
    drugs: list[tuple[str, str]] = field(default_factory=list)
    rep: Rep | None = None
    profile_phone: str = ""
    profile_as_of: date | None = None

    @property
    def address(self) -> str:
        return f"{self.street_no} {self.street} {self.suffix[0]}"

    @property
    def address_long(self) -> str:  # how a hospital registration desk might key it
        return f"{self.street_no} {self.street} {self.suffix[1]}"

    @property
    def age(self) -> int:
        years = REF_DATE.year - self.dob.year
        return years - ((REF_DATE.month, REF_DATE.day) < (self.dob.month, self.dob.day))


@dataclass
class Encounter:
    member: Member
    kind: str  # inpatient | ed
    facility: str
    start: datetime
    end: datetime
    patient_id: str
    authority: str
    with_claim: bool
    document: str | None  # received | missing | None
    dose_change: tuple[str, str] | None = None  # (drug_key, discharge strength)


class Background:
    def __init__(self, ds: Dataset, rng: random.Random) -> None:
        self.ds = ds
        self.rng = rng
        self.phones = PhonePool(rng)
        self.members: list[Member] = []
        self.chosen: dict[str, list[Member]] = {}
        self.encounters: list[Encounter] = []

    # --- helpers ---------------------------------------------------------------------------

    def day(self, start: date, end: date) -> date:
        return start + timedelta(days=self.rng.randint(0, (end - start).days))

    def moment(self, start: date, end: date, hours: tuple[int, int] = (8, 20)) -> datetime:
        return at(self.day(start, end), self.rng.randint(*hours), self.rng.choice((0, 15, 30, 45)))

    def weighted(self, options: tuple[tuple[str | None, int], ...]) -> str | None:
        values = [o for o, _ in options]
        return self.rng.choices(values, weights=[w for _, w in options])[0]

    def pick(self, imperfection: str, pool: list[Member]) -> list[Member]:
        if len(pool) < PER_KIND:
            raise RuntimeError(f"{imperfection}: only {len(pool)} eligible members")
        chosen = sorted(self.rng.sample(pool, PER_KIND), key=lambda m: m.member_id)
        self.chosen[imperfection] = chosen
        for member in chosen:
            self.ds.plant(imperfection, member.member_id, hero=False)
        return chosen

    def is_chosen(self, imperfection: str, member: Member) -> bool:
        return member in self.chosen.get(imperfection, [])

    # --- members ---------------------------------------------------------------------------

    def create_members(self) -> None:
        used_names: list[tuple[str, str]] = []
        for index in range(COUNT):
            sex = self.rng.choice(("F", "M"))
            while True:
                name = (self.rng.choice(FEMALE if sex == "F" else MALE), self.rng.choice(LAST))
                if name not in used_names:
                    used_names.append(name)
                    break
            lob = str(self.weighted(LOBS))
            low, high = {
                "MA-PPO": (66, 90),
                "DSNP": (66, 94),
                "DUAL": (28, 64),
                "MEDICAID": (19, 63),
            }[lob]
            age = self.rng.randint(low, high)
            dob = date(REF_DATE.year - age, self.rng.randint(1, 10), self.rng.randint(1, 28))
            pool = OLDER_ADULT_CONDITIONS if age >= 60 else YOUNGER_ADULT_CONDITIONS
            conditions = sorted(self.rng.sample(pool, self.rng.randint(1, 3)))
            drugs: list[tuple[str, str]] = []
            for key in conditions:
                options = CONDITION_BY_KEY[key].drugs
                if options:
                    drug = DRUG_BY_KEY[self.rng.choice(options)]
                    if all(d != drug.key for d, _ in drugs):
                        drugs.append((drug.key, self.rng.choice(drug.strengths)))
            city, zip_code = self.rng.choice(CITIES)
            phone = self.phones.take()
            phone_as_of = (
                None if self.rng.random() < 0.1 else self.day(date(2023, 1, 1), date(2026, 9, 30))
            )
            member = Member(
                member_id=f"SYN-{FIRST_ID + index:03d}",
                first=name[0],
                last=name[1],
                sex=sex,
                dob=dob,
                lob=lob,
                language=self.weighted(LANGUAGES),
                pcp=None if self.rng.random() < 0.1 else self.rng.choice(PCPS),
                phone=phone,
                phone_as_of=phone_as_of,
                street_no=self.rng.randint(2, 980),
                street=self.rng.choice(STREETS),
                suffix=self.rng.choice(SUFFIXES),
                city=city,
                zip=zip_code,
                address_as_of=self.day(date(2022, 1, 1), date(2026, 9, 30)),
                effective=self.day(date(2018, 1, 1), date(2026, 6, 1)).replace(day=1),
                cm=self.rng.choice(CMS),
                pharmacy=self.rng.choice(PHARMACIES),
                conditions=conditions,
                drugs=drugs,
                profile_phone=phone,
                profile_as_of=phone_as_of,
            )
            if age >= 80 and self.rng.random() < 0.4:
                member.rep = self.new_rep(member, self.day(date(2027, 1, 1), date(2028, 12, 31)))
            self.members.append(member)

    def new_rep(self, member: Member, expires: date) -> Rep:
        relationship = self.rng.choice(("daughter", "son", "spouse", "niece"))
        first = self.rng.choice(MALE if relationship == "son" else FEMALE)
        return Rep(f"{first} {member.last}", relationship, self.phones.take(), expires)

    # --- imperfection selection ------------------------------------------------------------

    def choose(self) -> None:
        everyone = self.members
        has_multi_strength = [
            m for m in everyone if any(len(DRUG_BY_KEY[d].strengths) > 1 for d, _ in m.drugs)
        ]
        has_30_day = [
            m for m in everyone if any(DRUG_BY_KEY[d].days_supply == 30 for d, _ in m.drugs)
        ]
        self.pick("I-01", everyone)
        self.pick("I-02", has_multi_strength)
        self.pick("I-03", has_30_day)
        self.pick("I-04", everyone)
        self.pick("I-05", everyone)
        self.pick("I-06", everyone)
        self.pick("I-07", [m for m in everyone if m.pcp])
        self.pick("I-08", [m for m in everyone if m.language not in ("en", None)])
        self.pick("I-09", everyone)
        # TCPA consent is per number, so a new number never inherits the old one's consent.
        self.chosen["I-11"] = self.chosen["I-09"]
        for member in self.chosen["I-11"]:
            self.ds.plant("I-11", member.member_id, hero=False)
        self.pick("I-10", everyone)
        self.pick("I-13", everyone)
        self.pick("I-14", [m for m in everyone if m.sex == "F"])
        self.pick("I-15", everyone)
        self.pick("I-17", everyone)
        planted = {i.id for i in IMPERFECTIONS if i.background}
        assert planted == set(self.chosen), sorted(planted ^ set(self.chosen))

        for member in self.chosen["I-09"]:
            member.profile_phone = self.phones.take()
            member.profile_as_of = self.day(date(2026, 9, 15), date(2026, 10, 30))
        for member in self.chosen["I-15"]:
            expired = self.day(date(2026, 6, 30), date(2026, 10, 31))
            if member.rep is None:
                member.rep = self.new_rep(member, expired)
            else:
                member.rep.expires = expired

    # --- encounters, ADT, claims, documents ------------------------------------------------

    def plan_encounters(self) -> None:
        def add(
            member: Member,
            kind: str,
            start: datetime,
            *,
            with_claim: bool,
            document: str | None,
            shell: bool = False,
            dose_change: tuple[str, str] | None = None,
        ) -> None:
            if kind == "inpatient":
                facility = self.rng.choice(INPATIENT_FACILITIES)
                end = at(
                    start.date() + timedelta(days=self.rng.randint(2, 5)),
                    self.rng.randint(10, 16),
                    self.rng.choice((0, 20, 40)),
                )
            else:
                facility = self.rng.choice(ED_FACILITIES)
                end = start + timedelta(
                    hours=self.rng.randint(3, 7), minutes=self.rng.choice((0, 25, 50))
                )
            self.encounters.append(
                Encounter(
                    member,
                    kind,
                    facility,
                    start,
                    end,
                    patient_id=f"{member.member_id}-H" if shell else member.member_id,
                    authority=facility if shell else "EVERGREEN",
                    with_claim=with_claim,
                    document=document if kind == "inpatient" else None,
                    dose_change=dose_change,
                )
            )

        pre = (date(2026, 6, 1), date(2026, 8, 31))
        post = (date(2026, 10, 1), date(2026, 11, 2))
        for member in sorted(self.rng.sample(self.members, 8), key=lambda m: m.member_id):
            kind = self.rng.choice(("inpatient", "ed"))
            add(member, kind, self.moment(*pre), with_claim=True, document="received")
        for member in self.chosen["I-01"]:
            add(
                member,
                "inpatient",
                self.moment(*pre),
                with_claim=True,
                document="received",
                shell=True,
            )
        for member in self.chosen["I-02"]:
            key, strength = next(
                (d, s) for d, s in member.drugs if len(DRUG_BY_KEY[d].strengths) > 1
            )
            other = next(s for s in DRUG_BY_KEY[key].strengths if s != strength)
            add(
                member,
                "inpatient",
                self.moment(*pre),
                with_claim=True,
                document="received",
                dose_change=(key, other),
            )
        for member in self.chosen["I-03"]:
            add(member, "inpatient", self.moment(*pre), with_claim=True, document="received")
        for member in self.chosen["I-04"]:
            add(member, "inpatient", self.moment(*pre), with_claim=True, document="missing")
        for member in self.chosen["I-05"]:
            add(member, "inpatient", self.moment(*post), with_claim=False, document="received")
        for member in self.chosen["I-10"]:
            add(
                member,
                "ed",
                self.moment(date(2026, 10, 1), date(2026, 11, 7), (6, 22)),
                with_claim=False,
                document=None,
            )
        self.encounters.sort(key=lambda e: (e.start, e.member.member_id))

    def emit_encounters(self) -> None:
        for enc in self.encounters:
            member = enc.member
            visit = self.ds.next_id("V")
            shell = enc.patient_id.endswith("-H")
            common: dict[str, Any] = dict(
                facility_code=enc.facility,
                facility_name=FACILITIES[enc.facility],
                patient_id=enc.patient_id,
                assigning_authority=enc.authority,
                last_name=member.last,
                first_name=member.first,
                dob=member.dob,
                sex=member.sex,
                # I-01: a registration-desk shell keys the address long-hand and has no phone.
                phone=None if shell else member.phone,
                address_line1=member.address_long if shell else member.address,
                city=member.city,
                zip=member.zip,
                visit_number=visit,
            )
            inpatient = enc.kind == "inpatient"
            first_delay = (
                timedelta(minutes=self.rng.randint(15, 90))
                if inpatient
                else timedelta(minutes=self.rng.randint(10, 540))
            )
            self.ds.adt.append(
                AdtEvent(
                    control_id=self.ds.next_id("ADT"),
                    trigger="A01" if inpatient else "A04",
                    event_at=enc.start,
                    received_at=enc.start + first_delay,
                    admit_at=enc.start,
                    discharge_at=None,
                    discharge_disposition=None,
                    patient_class="I" if inpatient else "E",
                    **common,
                )
            )
            self.ds.adt.append(
                AdtEvent(
                    control_id=self.ds.next_id("ADT"),
                    trigger="A03",
                    event_at=enc.end,
                    received_at=enc.end + timedelta(minutes=self.rng.randint(5, 60)),
                    admit_at=enc.start,
                    discharge_at=enc.end,
                    discharge_disposition="01",
                    patient_class="I" if inpatient else "E",
                    **common,
                )
            )

            codes = [CONDITION_BY_KEY[c].icd10 for c in member.conditions[:2]]
            if enc.with_claim:
                self.claim(
                    member,
                    "837I",
                    enc.kind,
                    enc.start.date(),
                    codes,
                    end=enc.end.date() if inpatient else None,
                )
            else:
                self.ds.mark_absent(
                    member.member_id,
                    "claims",
                    f"{enc.kind} claim for {enc.start.date()} (after cut-off)",
                    "I-05" if inpatient else "I-10",
                )
            if enc.document == "received":
                self.discharge_summary(enc, codes)
            elif enc.document == "missing":
                self.ds.add(
                    "hie_requests",
                    request_id=self.ds.next_id("REQ"),
                    member_id=member.member_id,
                    document_type="discharge_summary",
                    facility=FACILITIES[enc.facility],
                    requested_at=enc.end + timedelta(hours=2),
                    status="not_received",
                )
            self.gaps_for(enc)

    def discharge_summary(self, enc: Encounter, codes: list[str]) -> None:
        member = enc.member
        meds = []
        for key, strength in member.drugs:
            if enc.dose_change and enc.dose_change[0] == key:
                strength = enc.dose_change[1]
            drug = DRUG_BY_KEY[key]
            meds.append(Medication(drug.name, strength, f"{drug.name} {strength} {drug.sig}"))
        doc = CcdaDocument(
            doc_id=self.ds.next_id("DOC", 4),
            doc_type="discharge_summary",
            patient_id=enc.patient_id,
            last_name=member.last,
            first_name=member.first,
            dob=member.dob,
            sex=member.sex,
            facility=FACILITIES[enc.facility],
            effective_at=enc.end,
            received=enc.end.date(),
            encounter_start=enc.start,
            encounter_end=enc.end,
            disposition_code="01",
            disposition="Home or self care",
            problems=tuple(
                zip(codes, (CONDITION_LABELS[c] for c in member.conditions[:2]), strict=True)
            ),
            medications=tuple(meds),
            follow_up=("PCP follow-up within 7 days",),
        )
        self.ds.documents.append(doc)
        if self.rng.random() < 0.5:
            self.ds.add(
                "hie_requests",
                request_id=self.ds.next_id("REQ"),
                member_id=member.member_id,
                document_type="discharge_summary",
                facility=FACILITIES[enc.facility],
                requested_at=enc.end + timedelta(hours=1),
                status="received",
                received_at=enc.end + timedelta(hours=3),
            )

    def gaps_for(self, enc: Encounter) -> None:
        member = enc.member
        if enc.kind == "inpatient":
            due = enc.end.date()
            for _ in range(2):  # two business days after discharge
                due += timedelta(days=1)
                while due.weekday() >= 5:
                    due += timedelta(days=1)
            if due >= REF_DATE:
                self.ds.add(
                    "care_gaps",
                    gap_id=self.ds.next_id("GAP"),
                    member_id=member.member_id,
                    measure="TRC",
                    description="Transition contact after inpatient discharge",
                    anchor_date=enc.end.date(),
                    due_date=due,
                    status="open",
                )
        elif len(member.conditions) >= 2 and enc.end.date() + timedelta(days=7) >= REF_DATE:
            self.ds.add(
                "care_gaps",
                gap_id=self.ds.next_id("GAP"),
                member_id=member.member_id,
                measure="FMC",
                description="7-day follow-up after ED visit",
                anchor_date=enc.end.date(),
                due_date=enc.end.date() + timedelta(days=7),
                status="open",
            )

    def claim(
        self,
        member: Member,
        form: str,
        kind: str,
        service: date,
        codes: list[str],
        end: date | None = None,
    ) -> None:
        received = (end or service) + timedelta(days=self.rng.randint(3, 10))
        paid: date | None = received + timedelta(days=self.rng.randint(10, 25))
        status = "paid"
        if paid is not None and paid > CLAIMS_LOADED_THROUGH:
            status, paid = "pending", None
        self.ds.add(
            "claims_837",
            claim_id=self.ds.next_id("CLM"),
            member_id=member.member_id,
            claim_form=form,
            claim_type=kind,
            service_date=service,
            service_end_date=end,
            icd10_codes=codes,
            status=status,
            received_date=received,
            paid_date=paid,
            claims_loaded_through=CLAIMS_LOADED_THROUGH,
        )

    def office_visits(self) -> None:
        for member in self.members:
            for _ in range(self.rng.randint(1, 3)):
                codes = sorted(self.rng.sample(member.conditions, min(len(member.conditions), 2)))
                self.claim(
                    member,
                    "837P",
                    "office",
                    self.day(date(2026, 1, 5), date(2026, 9, 12)),
                    [CONDITION_BY_KEY[c].icd10 for c in codes],
                )

    # --- pharmacy --------------------------------------------------------------------------

    def fill(
        self,
        member: Member,
        drug: Drug,
        strength: str,
        day: date,
        prescriber: str | None,
        rejected: tuple[str, str] | None = None,
    ) -> None:
        sig = drug.sig
        per_day = 3 if "three times" in sig else 2 if "twice" in sig else 1
        unit_dose = any(w in sig for w in ("puff", "inhaled", "units", "weekly", "film"))
        quantity = Decimal(1 if unit_dose else drug.days_supply * per_day)
        if rejected or member.lob != "MA-PPO" or drug.tier is None:
            pay = Decimal("0.00")
        else:
            pay = TIER_COPAY[drug.tier]
        self.ds.add(
            "pharmacy_ncpdp",
            rx_claim_id=self.ds.next_id("RX"),
            member_id=member.member_id,
            fill_date=day,
            ndc=ndc(drug.key, strength),
            drug_name=drug.name,
            strength=strength,
            sig=sig,
            quantity=quantity,
            days_supply=drug.days_supply,
            claim_status="rejected" if rejected else "paid",
            reject_code=rejected[0] if rejected else None,
            reject_reason=rejected[1] if rejected else None,
            prescriber=prescriber,
            pharmacy_name=member.pharmacy,
            pharmacy_phone_on_profile=member.profile_phone,
            profile_phone_as_of=member.profile_as_of,
            patient_pay=None if rejected else pay,
        )

    def series(self, first: date, step: int, until: date = LAST_FILL) -> list[date]:
        days, current = [], first
        while current <= until:
            days.append(current)
            current += timedelta(days=step)
        return days

    def pharmacy(self) -> None:
        gap_admissions = {
            e.member.member_id: e
            for e in self.encounters
            if self.is_chosen("I-03", e.member) and e.kind == "inpatient"
        }
        for member in self.members:
            prescriber = member.pcp or "Dr R. Okafor"
            gap_drug = None
            if member.member_id in gap_admissions:
                gap_drug = next(d for d, _ in member.drugs if DRUG_BY_KEY[d].days_supply == 30)
            for key, strength in member.drugs:
                drug = DRUG_BY_KEY[key]
                step = drug.days_supply
                if key == gap_drug:
                    enc = gap_admissions[member.member_id]
                    # I-03: supply ends 3-6 days before the admission, resumes after discharge.
                    covered_until = enc.start.date() - timedelta(days=self.rng.randint(3, 6))
                    last_before = covered_until - timedelta(days=step)
                    before: list[date] = []
                    current = last_before
                    while current >= PHARMACY_HISTORY_START - timedelta(days=step - 1):
                        before.insert(0, current)
                        current -= timedelta(days=step)
                    days = before + self.series(enc.end.date() + timedelta(days=1), step)
                else:
                    first = PHARMACY_HISTORY_START - timedelta(days=self.rng.randint(0, step - 1))
                    days = self.series(first, step)
                for day in days:
                    self.fill(member, drug, strength, day, prescriber)
        for member in self.chosen["I-06"]:
            drug = DRUG_BY_KEY[self.rng.choice(NON_FORMULARY_BACKGROUND)]
            self.fill(
                member,
                drug,
                drug.strengths[0],
                self.day(date(2026, 8, 1), date(2026, 10, 31)),
                member.pcp or "Dr S. Brennan",
                rejected=("70", "non-formulary"),
            )
        for member in self.chosen["I-07"]:
            options = [
                k
                for k in ("atorvastatin", "lisinopril", "omeprazole", "levothyroxine")
                if all(k != d for d, _ in member.drugs)
            ]
            drug = DRUG_BY_KEY[self.rng.choice(options)]
            first = self.day(date(2026, 9, 28), date(2026, 10, 25))
            # Start after any recent discharge, so the hospital's list (which predates the
            # prescription) does not create an unplanned medication conflict.
            recent = [
                e.end.date()
                for e in self.encounters
                if e.member is member and e.kind == "inpatient" and e.end.date() >= first
            ]
            if recent:
                first = max(recent) + timedelta(days=1)
            for day in self.series(first, drug.days_supply):
                self.fill(member, drug, drug.strengths[0], day, member.pcp)
            self.ds.mark_absent(
                member.member_id,
                "claims",
                f"PCP visit around {first} (inferred from new prescription)",
                "I-07",
            )

    # --- other feeds -----------------------------------------------------------------------

    def eligibility(self) -> None:
        for member in self.members:
            rep = member.rep
            self.ds.add(
                "eligibility_834",
                member_id=member.member_id,
                last_name=member.last,
                first_name=member.first,
                dob=member.dob,
                sex=member.sex,
                plan=PLAN,
                lob=member.lob,
                state=STATE,
                language=member.language,
                pcp=member.pcp,
                phone=member.phone,
                phone_as_of=member.phone_as_of,
                address_line1=member.address,
                city=member.city,
                zip=member.zip,
                address_as_of=member.address_as_of,
                effective_date=member.effective,
                rep_name=rep.name if rep else None,
                rep_relationship=rep.relationship if rep else None,
                rep_form_expires=rep.expires if rep else None,
                medicaid_redetermination_due=self.day(date(2026, 12, 1), date(2027, 9, 30))
                if member.lob != "MA-PPO"
                else None,
            )
        for member in self.chosen["I-14"]:
            term = (member.effective - timedelta(days=self.rng.randint(30, 240))).replace(day=1)
            term -= timedelta(days=1)
            effective = (term - timedelta(days=self.rng.randint(365, 1100))).replace(day=1)
            city, zip_code = self.rng.choice(CITIES)
            self.ds.add(
                "eligibility_834",
                member_id=f"{member.member_id}-M",
                last_name=self.rng.choice(PREVIOUS_SURNAMES),
                first_name=member.first,
                dob=member.dob,
                sex=member.sex,
                plan=PLAN,
                lob=member.lob,
                state=STATE,
                language=member.language,
                phone=self.phones.take(),
                address_line1=f"{self.rng.randint(2, 980)} {self.rng.choice(STREETS)} St",
                city=city,
                zip=zip_code,
                effective_date=effective,
                term_date=term,
            )

    def labs(self) -> None:
        for member in self.members:
            for key in member.conditions:
                lab = CONDITION_BY_KEY[key].lab
                if lab is None:
                    continue
                loinc, name, unit = LABS[lab]
                for _ in range(self.rng.randint(1, 2)):
                    value = {
                        "hba1c": lambda: Decimal(self.rng.randint(61, 98)) / 10,
                        "ntprobnp": lambda: Decimal(self.rng.randint(250, 5200)),
                        "egfr": lambda: Decimal(self.rng.randint(30, 59)),
                    }[lab]()
                    self.ds.add(
                        "lab_results",
                        result_id=self.ds.next_id("LAB"),
                        member_id=member.member_id,
                        loinc=loinc,
                        test_name=name,
                        result_value=value,
                        unit=unit,
                        collected_date=self.day(date(2026, 2, 1), date(2026, 10, 20)),
                        source="Evergreen Lab Network",
                    )
            if "t2dm" in member.conditions and self.rng.random() < 0.5:
                self.ds.add(
                    "care_gaps",
                    gap_id=self.ds.next_id("GAP"),
                    member_id=member.member_id,
                    measure="PDC",
                    description="Diabetes medication adherence (PDC), year to date",
                    anchor_date=date(2026, 1, 1),
                    due_date=date(2026, 12, 31),
                    status="met",
                    value=Decimal(self.rng.randint(82, 97)) / 100,
                )

    def utilisation_management(self) -> None:
        for member in sorted(self.rng.sample(self.members, 8), key=lambda m: m.member_id):
            kind, item, code = self.rng.choice(UM_ITEMS)
            status = self.rng.choice(("approved", "approved", "denied", "pending"))
            if status == "pending":
                requested = self.day(date(2026, 10, 26), date(2026, 11, 6))
                due, decided = requested + timedelta(days=14), None
            else:
                requested = self.day(date(2026, 7, 1), date(2026, 10, 15))
                due = requested + timedelta(days=14)
                decided = requested + timedelta(days=self.rng.randint(2, 10))
            self.ds.add(
                "auth_requests",
                auth_id=self.ds.next_id("AUTH"),
                member_id=member.member_id,
                request_type=kind,
                item=item,
                item_code=code,
                requested_date=requested,
                status=status,
                decision_due=due,
                decision_date=decided,
                expedited=False,
                requested_by=member.pcp,
            )
        for member in self.chosen["I-17"]:
            kind, item, code = self.rng.choice(UM_ITEMS[:5])
            requested = self.day(date(2026, 10, 10), date(2026, 10, 25))
            due = min(requested + timedelta(days=self.rng.randint(7, 12)), date(2026, 11, 6))
            self.ds.add(
                "auth_requests",
                auth_id=self.ds.next_id("AUTH"),
                member_id=member.member_id,
                request_type=kind,
                item=item,
                item_code=code,
                requested_date=requested,
                status="pending",
                decision_due=due,
                expedited=False,
                missing_documents=self.rng.choice(MISSING_DOCS),
                requested_by=member.pcp,
            )

    def medicaid(self) -> None:
        medicaid_members = [m for m in self.members if m.lob != "MA-PPO"]
        for member in sorted(self.rng.sample(medicaid_members, 6), key=lambda m: m.member_id):
            hours = Decimal(self.rng.choice((8, 10, 12, 15, 20, 25)))
            reassessed = self.day(date(2026, 3, 1), date(2026, 9, 15))
            self.ds.add(
                "ltss_aide_hours",
                member_id=member.member_id,
                service="personal_care_aide",
                reassessment_date=reassessed,
                prior_hours_per_week=hours,
                authorized_hours_per_week=hours,
                effective_date=reassessed,
                notice_date=reassessed,
                appeal_window_days=60,
                as_of=LOAD_DATES["ltss"],
            )
        for member in sorted(self.rng.sample(medicaid_members, 6), key=lambda m: m.member_id):
            for _ in range(self.rng.randint(1, 2)):
                self.ds.add(
                    "nemt_trips",
                    trip_id=self.ds.next_id("TRIP"),
                    member_id=member.member_id,
                    trip_date=self.day(date(2026, 9, 1), date(2026, 10, 30)),
                    pickup_address=f"{member.address}, {member.city}",
                    destination=f"{member.pcp or 'Northfield Family Health'} clinic",
                    status="completed",
                    as_of=date(2026, 10, 31),
                )

    def sdoh(self) -> None:
        for member in self.members:
            if self.rng.random() < 0.6:
                self.ds.add(
                    "screens",
                    screen_id=self.ds.next_id("SCR"),
                    member_id=member.member_id,
                    instrument="HRA",
                    domain="general",
                    screen_date=self.day(date(2025, 12, 1), date(2026, 10, 31)),
                    result=self.rng.choice(
                        (
                            "Lives alone; independent",
                            "Lives with spouse; independent",
                            "Lives with family; needs help with transport",
                        )
                    ),
                    risk_level=self.rng.choice(("low", "moderate")),
                )
            if self.is_chosen("I-13", member):
                # I-13: old "stable" screen, contradicted by returned mail in October.
                self.ds.add(
                    "screens",
                    screen_id=self.ds.next_id("SCR"),
                    member_id=member.member_id,
                    instrument="AHC-HRSN",
                    domain="housing",
                    screen_date=self.day(date(2025, 10, 15), date(2025, 12, 20)),
                    result="Stable",
                    risk_level="low",
                )
            elif member.lob != "MA-PPO" and self.rng.random() < 0.5:
                unstable = self.rng.random() < 0.3
                self.ds.add(
                    "screens",
                    screen_id=self.ds.next_id("SCR"),
                    member_id=member.member_id,
                    instrument="AHC-HRSN",
                    domain="housing",
                    screen_date=self.day(date(2026, 4, 1), date(2026, 10, 31)),
                    result="Housing unstable" if unstable else "Stable",
                    risk_level="moderate" if unstable else "low",
                )
            if member.rep is not None:
                score = self.rng.randint(3, 10)
                self.ds.add(
                    "screens",
                    screen_id=self.ds.next_id("SCR"),
                    member_id=member.member_id,
                    instrument="ZBI-4",
                    domain="caregiver_strain",
                    screen_date=self.day(date(2026, 3, 1), date(2026, 10, 31)),
                    result="Caregiver burden screened",
                    score=score,
                    score_max=16,
                    risk_level="moderate" if score >= 8 else "low",
                )

    def cm_platform(self) -> None:
        def outreach(
            member: Member,
            phone: str | None,
            when: datetime,
            outcome: str,
            language: str | None,
            channel: str = "call",
        ) -> None:
            self.ds.add(
                "outreach",
                outreach_id=self.ds.next_id("OUT"),
                member_id=member.member_id,
                phone=phone,
                channel=channel,
                attempted_at=when,
                outcome=outcome,
                language_used=language,
                cm_name=member.cm,
            )

        october = (date(2026, 10, 1), date(2026, 10, 30))
        for member in self.members:
            last_outcome: str | None = None
            if self.is_chosen("I-08", member):
                for when in sorted(
                    self.moment(*october, (9, 17)) for _ in range(self.rng.randint(3, 4))
                ):
                    outreach(member, member.phone, when, "voicemail", "en")
                last_outcome = "voicemail"
            elif self.is_chosen("I-09", member):
                outreach(
                    member,
                    member.phone,
                    self.moment(*october, (9, 17)),
                    "disconnected",
                    member.language,
                )
                last_outcome = "disconnected"
            elif self.rng.random() < 0.5:
                for when in sorted(
                    self.moment(*october, (9, 17)) for _ in range(self.rng.randint(1, 2))
                ):
                    last_outcome = self.rng.choice(("answered", "voicemail", "no_answer"))
                    outreach(member, member.phone, when, last_outcome, member.language)
            if self.is_chosen("I-13", member):
                outreach(
                    member,
                    None,
                    self.moment(*october),
                    "returned_undeliverable",
                    None,
                    channel="mail",
                )

            disconnected = self.is_chosen("I-09", member)
            self.ds.add(
                "contact_points",
                contact_id=self.ds.next_id("CP"),
                member_id=member.member_id,
                phone=member.phone,
                owner_type="member",
                owner_name=f"{member.first} {member.last}",
                source="eligibility",
                last_verified=member.phone_as_of,
                last_outcome=last_outcome,
                confidence=Decimal("0.05")
                if disconnected
                else Decimal(self.rng.randint(45, 85)) / 100,
                authorized=True,
            )
            if disconnected:
                self.ds.add(
                    "contact_points",
                    contact_id=self.ds.next_id("CP"),
                    member_id=member.member_id,
                    phone=member.profile_phone,
                    owner_type="member",
                    owner_name=f"{member.first} {member.last} (likely)",
                    source="pharmacy",
                    last_verified=member.profile_as_of,
                    last_outcome="not_tried",
                    confidence=Decimal(self.rng.randint(65, 75)) / 100,
                    authorized=True,
                )
            if member.rep is not None:
                self.ds.add(
                    "contact_points",
                    contact_id=self.ds.next_id("CP"),
                    member_id=member.member_id,
                    phone=member.rep.phone,
                    owner_type="representative",
                    owner_name=member.rep.name,
                    relationship=member.rep.relationship,
                    source="representative form",
                    confidence=Decimal(self.rng.randint(60, 85)) / 100,
                    authorized=True,
                )
                self.ds.add(
                    "consents",
                    consent_id=self.ds.next_id("CON"),
                    member_id=member.member_id,
                    consent_type="personal_representative",
                    representative_name=member.rep.name,
                    relationship=member.rep.relationship,
                    granted_date=member.rep.expires.replace(year=member.rep.expires.year - 2),
                    expires_date=member.rep.expires,
                    source="representative form",
                )

            # I-09/I-11: the old number has SMS consent; the new pharmacy number has none.
            if disconnected or self.rng.random() < 0.4:
                self.ds.add(
                    "consents",
                    consent_id=self.ds.next_id("CON"),
                    member_id=member.member_id,
                    consent_type="tcpa_sms",
                    phone=member.phone,
                    granted_date=self.day(date(2024, 1, 1), date(2026, 8, 31)),
                    source="enrolment form",
                )

            needs_language = member.language not in ("en", "es", None)
            self.ds.add(
                "preferences",
                member_id=member.member_id,
                preferred_language=member.language,
                proxy_language="en" if member.rep and needs_language else None,
                assigned_cm="Luis" if member.language == "es" else member.cm,
                cm_language_required=member.language if needs_language else None,
            )

    def run(self) -> None:
        self.create_members()
        self.choose()
        self.plan_encounters()
        self.eligibility()
        self.office_visits()
        self.emit_encounters()
        self.pharmacy()
        self.labs()
        self.utilisation_management()
        self.medicaid()
        self.sdoh()
        self.cm_platform()
        self.risk()  # last, so earlier feeds keep the same random sequence

    def risk(self) -> None:
        # About 10% of members have no plan risk score (scoring then uses the cohort median).
        for member in self.members:
            if self.rng.random() < 0.1:
                continue
            self.ds.add(
                "risk_scores",
                member_id=member.member_id,
                model="Evergreen readmission risk v3",
                score=Decimal(self.rng.randint(12, 86)) / 100,
                scored_at=date(2026, 11, 1),
            )


def add_background(ds: Dataset, rng: random.Random) -> None:
    Background(ds, rng).run()
