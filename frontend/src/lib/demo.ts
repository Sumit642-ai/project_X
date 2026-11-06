import { useApi } from "./useApi";

export interface DemoConfig {
  demo_mode: boolean;
  users: { username: string; label: string }[];
}

export interface DemoStep {
  id: string;
  label: string;
  story: string;
  at: string;
  applied: boolean;
  available: boolean;
}

export interface DemoState {
  instant: string;
  steps: DemoStep[];
  paused_feeds: string[];
  held_feeds: string[];
  ai_timeout: boolean;
  kayla_part2_consent: "valid" | "expired";
  cm_mode: string;
  recent_loads: { id: number; file: string; status: string; active: boolean; error: string | null }[];
  unmapped_codes: { code_system: string; code: string | null; display: string | null; source_stream: string; occurrences: number }[];
}

/** Public: whether demo mode is on (and, if so, the seeded users for the sign-in page). */
export function useDemoConfig() {
  return useApi<DemoConfig>("/demo/config");
}
