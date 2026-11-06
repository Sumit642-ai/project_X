// Shapes returned by the CaseCompass API (see /docs). Decimals arrive as strings.

export type Freshness = "green" | "amber" | "red" | "grey";

export interface Unknown {
  value: "UNKNOWN";
  type: string;
  key: string | null;
  reason: string;
  as_of: string | null;
}

export interface User {
  username: string;
  name: string;
  role: "cm" | "supervisor" | "call_agent";
  credential: string | null;
  program: string | null;
  licensed_states: string[];
  languages: string[];
}

export interface QueueRow {
  rank: number;
  member_id: string;
  name: string;
  lob: string | null;
  age: number | null;
  score_inputs: { r: string; u: string; m: string; a: string };
  tier: "T0" | "T1" | "T2";
  score: string;
  why: string[];
  due_at: string | null;
  due_tz: string | null;
  next_best_action: { text: string; reason: string; rule_id: string } | null;
  duplicate: { flagged: boolean; label: string | null; link_ids: number[] };
  assigned_cm: string | null;
}

export interface StaleFeed {
  feed: string;
  stream: string;
  reason: string;
}

export interface QueueOut {
  header: {
    now: string;
    data_as_of: string | null;
    scored_on: string | null;
    stale_feeds: StaleFeed[];
    tier_counts: Record<string, number>;
    capacity: { active: number; target: number | null } | null;
  };
  rows: QueueRow[];
}

export interface Fact {
  id: number;
  type: string;
  key: string;
  value: Record<string, unknown>;
  event_date: string | null;
  loaded_at: string;
  source_system: string;
  source_record_id: string;
  status: string;
  confidence: string;
  freshness: Freshness;
  masked: boolean;
}

export interface Signal {
  rule_id: string;
  severity: "red" | "amber" | "info";
  insight_text: string;
  suggested_step: string;
  due_at: string | null;
  input_fact_ids: number[];
}

export interface Conflict {
  label: string;
  id: number;
  fact_type: string;
  key: string;
  kind: string;
  summary: string;
  status: string;
  fact_ids: number[];
  detected_at: string;
}

export interface Contact {
  number: string;
  owner: string;
  owner_name: string | null;
  relationship: string | null;
  source: string | null;
  last_verified: string | null;
  last_outcome: string | null;
  best_window: string | null;
  confidence: string;
  consent_sms: boolean;
  authorised: boolean;
  callable: boolean;
  not_callable_reason: string | null;
}

export interface Consent {
  id: number;
  type: string;
  party: string | null;
  phone: string | null;
  program: string | null;
  scope: string | null;
  valid_from: string;
  valid_to: string | null;
  valid: boolean;
}

export interface DocumentRow {
  id: number;
  type: string;
  facility: string | null;
  status: string;
  requested_at: string | null;
  received_at: string | null;
}

export interface PendingLink {
  id: number;
  source_system: string;
  source_record_id: string;
  confidence: string;
  status: string;
  label: string;
}

export interface Member360 {
  now: string;
  claims_as_of: string | null;
  member: {
    member_id: string;
    name: string;
    dob: string;
    age: number;
    lob: string | null;
    plan: string | null;
    language: string | null;
    proxy_language: string | null;
    assigned_cm: string | null;
  };
  since_last_contact: { reference: string; since: string | null; facts: Fact[]; signals: Signal[] };
  last_call_note: Unknown;
  member_goal: Unknown;
  conflicts: Conflict[];
  contacts: Contact[];
  care_team: { role: string; name: string | Unknown; detail: string | null }[];
  documents: DocumentRow[];
  consents: Consent[];
  facts: Fact[];
  unknowns: Unknown[];
  risk: { value: string | Unknown; basis: string; verify: boolean; model: string | null; scored_at: string | null };
  pending_links: PendingLink[];
  adt_feed_stale?: boolean;
}

export interface Part2Reveal {
  member_id: string;
  consent_id: number;
  audit_event_id: number;
  notes: {
    fact_id: number;
    service_date: string | null;
    program: string | null;
    note_type: string | null;
    counselor: string | null;
    note_text: string | null;
  }[];
  redisclosure_notice: string;
}

export function isUnknown(value: unknown): value is Unknown {
  return typeof value === "object" && value !== null && (value as Unknown).value === "UNKNOWN";
}
