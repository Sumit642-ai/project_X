import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";

import { DemoAdminPage } from "./DemoAdminPage";
import { TasksPage } from "./OtherPages";

afterEach(() => vi.unstubAllGlobals());

function stub(routes: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string) => {
      const key = Object.keys(routes).find((path) => url.endsWith(path));
      return Promise.resolve(new Response(JSON.stringify(key ? routes[key] : {}), { status: 200 }));
    }),
  );
}

const TASK = {
  id: 1,
  member_id: "SYN-001",
  kind: "prescriber_message",
  title: "Message prescriber: confirm loop-diuretic dose and supply",
  due_date: "2026-11-10",
  status: "open",
  signal_rule_id: "NO_CRITICAL_MED_ON_HAND",
  signal_input_fact_ids: [12],
};

test("a task resolved by data turns green and names the resolving facts", async () => {
  stub({
    "/tasks": [
      { ...TASK, status: "done", resolution: "Resolved by data: Furosemide 80 mg filled 2026-11-09", resolution_fact_ids: [1720] },
      { ...TASK, id: 2, kind: "pcp_visit_ride", title: "Book PCP follow-up visit and ride" },
    ],
  });
  render(
    <MemoryRouter>
      <TasksPage />
    </MemoryRouter>,
  );
  const cards = await screen.findAllByTestId("task-card");
  expect(cards[0]).toHaveAttribute("data-status", "done");
  expect(cards[0].className).toContain("bg-green-50");
  expect(cards[0]).toHaveTextContent("✓ Resolved by data: Furosemide 80 mg filled 2026-11-09 (fact 1720)");
  expect(cards[1].className).not.toContain("bg-green-50");
});

test("the operator panel shows each toggle's state, loads and the unmapped report", async () => {
  stub({
    "/demo/config": { demo_mode: true, users: [] },
    "/demo/state": {
      instant: "2026-11-09T08:00:00-05:00",
      steps: [{ id: "mon_1400", label: "Monday 14:00", story: "Fill arrives.", at: "2026-11-09T14:00:00-05:00", applied: false, available: true }],
      paused_feeds: ["pharmacy"],
      held_feeds: [],
      ai_timeout: false,
      kayla_part2_consent: "expired",
      cm_mode: "down",
      recent_loads: [{ id: 9, file: "pharmacy/pharmacy_ncpdp_20261109.csv", status: "QUARANTINE", active: false, error: "schema change" }],
      unmapped_codes: [{ code_system: "NDC", code: "99999-0042-30", display: "Zorvantide 5 mg", source_stream: "pharmacy_ncpdp", occurrences: 1 }],
    },
  });
  render(
    <MemoryRouter>
      <DemoAdminPage />
    </MemoryRouter>,
  );
  expect(await screen.findByRole("button", { name: "Resume pharmacy feed" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Pause ADT feed" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Restore CM platform" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Restore Kayla's Part 2 consent" })).toBeInTheDocument();
  expect(screen.getByTestId("recent-loads")).toHaveTextContent("QUARANTINE");
  expect(screen.getByTestId("unmapped-codes")).toHaveTextContent("Zorvantide 5 mg");
});

test("the operator panel is off outside demo mode", async () => {
  stub({ "/demo/config": { demo_mode: false, users: [] } });
  render(
    <MemoryRouter>
      <DemoAdminPage />
    </MemoryRouter>,
  );
  expect(await screen.findByText(/Demo mode is off/)).toBeInTheDocument();
});

test("the metrics page shows override, AI, write-back and feed metrics, UNKNOWN when there is no data", async () => {
  const { MetricsPage } = await import("./MetricsPage");
  stub({
    "/admin/metrics": {
      at: "2026-11-09T08:00:00-05:00",
      feeds: [{ feed: "claims", stream: "claims_837", age_hours: 1, stale: true, reason: "data as of 2026-09-25 (45 days)" }],
      signals_per_rule: { run_day: "2026-11-09", counts: { NO_CRITICAL_MED_ON_HAND: 1 } },
      override_rate: { window_days: 7, rate: 0.5, overrides: { override_not_now: 1 }, calls_started: 1 },
      ai: { drafts: 0, sentences: 0, unsupported_sentence_rate: null, major_edit_ratio: null },
      writeback: { pending: 1, oldest_pending_seconds: 0, alerted: 0, synced: 0, median_sync_lag_seconds: null },
    },
  });
  render(
    <MemoryRouter>
      <MetricsPage />
    </MemoryRouter>,
  );
  expect(await screen.findByTestId("metric-override")).toHaveTextContent("50%");
  expect(screen.getByTestId("metric-ai")).toHaveTextContent("UNKNOWN");
  expect(screen.getByTestId("metric-writeback")).toHaveTextContent("1");
  expect(screen.getByTestId("metric-feeds")).toHaveTextContent("stale: data as of 2026-09-25");
  expect(screen.getByTestId("metric-signals")).toHaveTextContent("NO_CRITICAL_MED_ON_HAND: 1");
});
