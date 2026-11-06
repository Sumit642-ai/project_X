export interface LadderEntry {
  number: string;
  channel: "phone" | "sms" | "video";
  owner: string;
  owner_name: string | null;
  confidence: string;
  best_window: string | null;
  best_start: string | null;
  authorised: boolean;
  callable: boolean;
  reason: string;
}

export interface CallPlan {
  member_id: string;
  member_name: string;
  language: string | null;
  proxy_language: string | null;
  summary: string;
  ladder: LadderEntry[];
  opening_script: string;
  identity_step: string;
  voicemail_script: string;
  resumable_encounter_id: number | null;
}

export interface EncounterField {
  field_id: string;
  group: string;
  label: string;
  risk: "high" | "low";
  status: "prefilled_fresh" | "prefilled_stale" | "live_only";
  reason: string | null;
  prefill: unknown;
  source_fact_ids: number[];
  source_as_of: string | null;
  answer: unknown;
  confirmed: boolean;
  method: string | null;
  time_on_field_ms: number | null;
}

export interface CallTask {
  id: number;
  member_id: string;
  kind: string;
  title: string;
  due_date: string;
  status: string;
  signal_rule_id: string | null;
  signal_input_fact_ids: number[];
  resolved_at?: string | null;
  resolution?: string | null;
  resolution_fact_ids?: number[];
}

export interface EncounterOut {
  id: number;
  member_id: string;
  outcome: string | null;
  status: string;
  number_used: string;
  identity_verified: boolean;
  transcription_consent: boolean;
  notes: string | null;
  autosave: { pane?: Pane; notes?: string; transcription_consent?: boolean } | null;
  counts: Record<"prefilled_fresh" | "prefilled_stale" | "live_only", number>;
  fields: EncounterField[];
  tasks: CallTask[];
}

export type Pane = "pre" | "live" | "wrap";

export function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "UNKNOWN";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(show).join("; ");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== null && v !== undefined)
      .map(([k, v]) => `${k.replace(/_/g, " ")}: ${show(v)}`)
      .join(", ");
  }
  return String(value);
}

export interface DraftSentence {
  section: "summary" | "note";
  text: string;
  source_turns: number[];
  status: "supported" | "unsupported" | "blocked";
  reasons: string[];
  flagged_medications: string[];
}

export interface AiDraft {
  id: number;
  sentences: DraftSentence[];
  open_questions: string[];
  flagged_medications: string[];
  unsupported_count: number;
  blocked_count: number;
  note_text: string;
  turns: { number: number; speaker: string; text: string }[];
}

export interface DraftResponse {
  enabled: boolean;
  available: boolean;
  reason: string | null;
  draft: AiDraft | null;
}
