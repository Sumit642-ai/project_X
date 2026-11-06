// Formatting helpers. Times are always shown in the member's (or plan's) time zone and
// measured against the server Clock, never the browser's clock.

export const PLAN_TZ = "America/New_York";

/** ".88", "1.0", ".725": the compact style used in score explanations. */
export function compact(value: string | number): string {
  const n = Number(value);
  if (n === 1) return "1.0";
  if (n === 0) return "0";
  const text = String(Number(n.toFixed(3)));
  return text.startsWith("0.") ? text.slice(1) : text;
}

export function scoreText(inputs: { r: string; u: string; m: string; a: string }, score: string): string {
  return (
    `Risk ${compact(inputs.r)} x40 + Urgency ${compact(inputs.u)} x30 + ` +
    `Fixable ${compact(inputs.m)} x20 + Reach ${compact(inputs.a)} x10 = ${score}`
  );
}

export function shortDate(iso: string | null, timeZone = PLAN_TZ): string {
  if (!iso) return "UNKNOWN";
  const date = iso.length === 10 ? new Date(`${iso}T12:00:00Z`) : new Date(iso);
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone }).format(date);
}

export function longDate(iso: string | null, timeZone = PLAN_TZ): string {
  if (!iso) return "UNKNOWN";
  const date = iso.length === 10 ? new Date(`${iso}T12:00:00Z`) : new Date(iso);
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone,
  }).format(date);
}

export function clockTime(iso: string, timeZone = PLAN_TZ): string {
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone,
  }).format(new Date(iso));
}

export function hoursBetween(fromIso: string, toIso: string): number {
  return (new Date(toIso).getTime() - new Date(fromIso).getTime()) / 3_600_000;
}

export function daysBetween(fromIso: string, toIso: string): number {
  return Math.floor((new Date(toIso).getTime() - new Date(`${fromIso.slice(0, 10)}T00:00:00Z`).getTime()) / 86_400_000);
}

const SOURCE_LABELS: Record<string, string> = {
  pharmacy_ncpdp: "PBM",
  claims_837: "Claims",
  adt: "ADT",
  ccda: "Hospital document",
  eligibility_834: "Eligibility",
  lab_results: "Lab",
  care_gaps: "Care gaps",
  screens: "SDOH screen",
  consents: "CM platform",
  contact_points: "CM platform",
  outreach: "CM platform",
  preferences: "CM platform",
  ltss_aide_hours: "Medicaid LTSS",
  nemt_trips: "Medicaid NEMT",
  auth_requests: "UM",
  hie_requests: "HIE",
  new_dawn_notes: "Part 2 program",
  risk_scores: "Plan risk model",
  cm_workbench: "Workbench",
};

const EVENT_LABELS: Record<string, string> = {
  medication: "fill",
  lab: "collected",
  sdoh: "screened",
  diagnosis: "coded",
  event: "event",
  contact_point: "verified",
  coverage: "effective",
  care_gap: "opened",
  consent: "granted",
  service: "as of",
  risk: "scored",
};

export function sourceLabel(sourceSystem: string): string {
  return SOURCE_LABELS[sourceSystem] ?? sourceSystem;
}

export function freshnessTooltip(sourceSystem: string, type: string, eventDate: string | null, value?: Record<string, unknown>): string {
  let what = EVENT_LABELS[type] ?? "dated";
  if (type === "medication" && value?.source_kind === "hospital_document") what = "listed";
  return `${sourceLabel(sourceSystem)} · ${what} ${eventDate ? shortDate(eventDate) : "UNKNOWN"}`;
}

const LANGUAGES: Record<string, string> = {
  en: "English",
  es: "Spanish",
  vi: "Vietnamese",
  ht: "Haitian Creole",
  so: "Somali",
  ar: "Arabic",
  ne: "Nepali",
};

export function languageName(code: string | null): string {
  return code ? (LANGUAGES[code] ?? code) : "UNKNOWN";
}

export function describeFact(fact: { type: string; key: string; value: Record<string, unknown>; masked: boolean }): string {
  const v = fact.value;
  if (fact.masked) return "Restricted record (42 CFR Part 2)";
  switch (fact.type) {
    case "medication": {
      const status = v.dispensed === false ? ` (${String(v.reject_reason ?? "rejected")})` : "";
      return `${String(v.product ?? fact.key)} ${String(v.strength ?? "")}${status}`.trim();
    }
    case "diagnosis":
      return `${String(v.display ?? fact.key)}${v.code ? ` (${String(v.code)})` : ""}`;
    case "lab":
      return `${String(v.test_name ?? fact.key)} ${v.value == null ? "UNKNOWN" : String(Number(v.value))} ${String(v.unit ?? "")}`.trim();
    case "risk":
      return `Plan risk score ${v.score == null ? "UNKNOWN" : compact(String(v.score))} (${String(v.model ?? "model UNKNOWN")})`;
    case "coverage":
      if (fact.key.startsWith("plan:")) return `Coverage: ${String(v.plan ?? "")} ${String(v.lob ?? "")}, PCP ${String(v.pcp ?? "UNKNOWN")}`;
      return `Authorisation: ${String(v.item ?? fact.key)} (${String(v.status ?? "")})`;
    case "consent":
      return `Consent: ${fact.key.replace(/_/g, " ")}${v.representative_name ? ` · ${String(v.representative_name)}` : ""}${v.phone ? ` · ${String(v.phone)}` : ""}`;
    case "preference":
      return `Language preference: ${languageName((v.preferred_language as string | null) ?? null)}`;
    case "service":
      return `Service: ${fact.key.replace(/_/g, " ")}`;
    case "sdoh":
      return `${String(v.instrument ?? "Screen")}: ${String(v.result ?? "UNKNOWN")}`;
    case "event":
      if (fact.key.startsWith("adt:")) return `ADT ${fact.key.slice(4)} at ${String(v.facility ?? "UNKNOWN")}`;
      if (fact.key.startsWith("claim:")) return `Claim: ${fact.key.slice(6)} (${String(v.status ?? "")})`;
      if (fact.key.startsWith("outreach:")) return `Outreach ${String(v.channel ?? "")}: ${String(v.outcome ?? "")}`;
      if (fact.key.startsWith("document")) return `${fact.key.replace(/_/g, " ").replace(":", ": ")}`;
      return fact.key;
    case "care_gap":
      return `Care gap ${fact.key}: due ${String(v.due_date ?? "UNKNOWN")}`;
    case "contact_point":
      return `Contact ${String(v.number ?? fact.key)} (${String(v.source ?? "")})`;
    default:
      return `${fact.type}: ${fact.key}`;
  }
}
