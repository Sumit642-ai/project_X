// The 15-minute demo script (docs/DEMO.md), end to end, in under 3 minutes.
// Opening (the old way), happy path for Raymond, then breaks 1-4. Runs against the demo build;
// it resets the demo first and last, so the other specs start from the pristine data.
import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import { signIn } from "./helpers";

test.describe.configure({ mode: "serial" });

// Leave the pristine demo data for the other specs, even if the script fails part-way.
test.afterEach(async ({ request }) => {
  const login = await request.post("/api/auth/login", { data: { username: "janet" } });
  const { access_token: token } = (await login.json()) as { access_token: string };
  await request.post("/api/demo/clock/reset", { headers: { Authorization: `Bearer ${token}` } });
});

async function switchUser(page: Page, username: string): Promise<void> {
  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, username);
}

/** The presenter's second tab: the operator panel. */
async function operator(context: BrowserContext): Promise<(label: string) => Promise<string>> {
  const panel = await context.newPage();
  await panel.goto("/demo-admin");
  return async (label: string) => {
    await panel.bringToFront();
    await panel.goto("/demo-admin");
    await panel.getByTestId("demo-admin").getByRole("button", { name: label, exact: true }).click();
    const message = panel.getByTestId("demo-message");
    await expect(message).toContainText(`${label}: done`, { timeout: 30_000 }); // a data refresh takes seconds
    return (await message.textContent()) ?? "";
  };
}

async function resetDemo(page: Page): Promise<void> {
  await page.goto("/demo-admin");
  await page.getByTestId("demo-admin").getByRole("button", { name: "Reset demo" }).click();
  await expect(page.getByTestId("demo-clock-time")).toHaveText(/Mon 9 Nov.*08:00/, { timeout: 30_000 });
}

test("the 15-minute demo script runs end to end", async ({ page, context, request }) => {
  test.setTimeout(180_000);
  const started = Date.now();

  // Opening: the old way, seven portal tabs.
  await page.goto("/demo/old-way");
  await expect(page.getByRole("tab")).toHaveCount(7);
  await page.getByRole("tab", { name: /HIE viewer/ }).click();
  await expect(page.getByRole("tabpanel")).toContainText("Furosemide 80 mg daily");
  await page.getByRole("link", { name: /Now the same member in CaseCompass/ }).click();
  await expect(page.getByRole("button", { name: /Sign in as Maria/ })).toBeVisible(); // seeded users, demo only
  await signIn(page, "maria");
  await resetDemo(page);

  // Happy path: Raymond.
  await page.goto("/queue");
  const first = page.getByTestId("queue-row").first();
  await expect(first).toHaveAttribute("data-member", "SYN-001");
  await expect(first).toContainText("T0");
  await first.getByRole("link", { name: "Open Raymond Tull" }).click();
  await page.getByTestId("match-banner").getByRole("button", { name: "Same person: confirm" }).click();
  await expect(page.getByTestId("match-banner")).toHaveCount(0);
  await expect(page.locator("body")).toContainText("Furosemide");
  await page.getByRole("link", { name: "Start call" }).click();
  await page.getByTestId("pre-call").getByRole("button", { name: /Dial 555-0142/ }).click();
  const live = page.getByTestId("live-pane");
  await live.getByRole("button", { name: "Name and date of birth verified" }).click();
  await live.getByLabel("Member agreed to transcription").check();
  await live.getByLabel("Nurse notes").fill("Spoke with Raymond and Joan. No furosemide at home; weight up 2 lb.");
  await live.getByRole("button", { name: "Go to wrap-up" }).click();
  const wrap = page.getByTestId("wrap-pane");
  const highRisk = wrap.getByTestId("high-risk-field");
  for (let i = 0; i < 6; i++) {
    await highRisk.nth(i).getByRole("button", { name: /^Confirm / }).click();
    await expect(highRisk.nth(i)).toContainText("Confirmed one by one");
  }
  await wrap.getByRole("button", { name: "Confirm 16 low-risk fields" }).click();
  await wrap.getByRole("button", { name: "End call and create tasks" }).click();
  await expect(page.getByTestId("task-list")).toContainText("Message prescriber");

  // Break 1: the CM platform goes down at save; the save waits and syncs exactly once.
  const op = await operator(context);
  await op("Take CM platform down");
  await page.bringToFront();
  await wrap.getByRole("button", { name: "Save to record" }).click();
  await expect(page.getByTestId("sync-status")).toContainText("Saved here, syncing to record");
  expect(await op("Restore CM platform")).toContain("1 waiting save(s) synced");
  await page.bringToFront();
  await page.waitForURL("**/queue", { timeout: 20_000 }); // the wrap-up pane sees "synced" and moves on
  const entries = await (await request.get("http://127.0.0.1:8200/admin/entries?member_id=SYN-001")).json();
  expect(entries).toHaveLength(1);

  // Break 2: the pharmacy feed pauses; the queue says so.
  await op("Pause pharmacy feed");
  await page.bringToFront();
  await page.reload();
  await expect(page.getByTestId("stale-banner")).toContainText("pharmacy (feed paused at the data layer");
  await op("Resume pharmacy feed");

  // Break 3: Kayla. A 0.78 match waits for a person; Part 2 needs valid consent.
  await page.bringToFront();
  await switchUser(page, "alma");
  await page.getByRole("link", { name: "Open Kayla Morrison" }).click();
  await expect(page.getByTestId("match-banner")).toContainText("SYN-004-M");
  await expect(page.getByTestId("match-banner")).toContainText("match confidence 0.78");
  await op("Expire Kayla's Part 2 consent");
  await page.bringToFront();
  await page.reload();
  const panel = page.getByTestId("part2-panel");
  await expect(page.getByRole("list", { name: "Consents" })).toContainText("Part 2 · Evergreen · expired 2026-11-08");
  await expect(panel).toContainText("No valid Part 2 consent on file: records cannot be revealed.");
  await expect(panel.getByRole("button", { name: "Reveal restricted records" })).toHaveCount(0);
  const refused = await page.evaluate(async () => {
    const response = await fetch("/api/members/SYN-004/part2/reveal", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("casecompass.token")}` },
      body: JSON.stringify({ reason: "Coordinate MOUD with the Riverside clinic" }),
    });
    return response.status;
  });
  expect(refused).toBe(403); // the server refuses too, not just the screen
  await op("Restore Kayla's Part 2 consent");
  await page.bringToFront();
  await page.reload();
  await panel.getByRole("button", { name: "Reveal restricted records" }).click();
  await panel.getByLabel(/Reason/).fill("Coordinate MOUD with the Riverside clinic");
  await panel.getByRole("button", { name: "Reveal (audited)" }).click();
  await expect(page.getByTestId("part2-notes")).toContainText("42 CFR Part 2");

  // Break 4: the clock moves to 14:00; the furosemide fill arrives and the task turns green.
  await switchUser(page, "maria");
  await page.goto("/tasks");
  const diuretic = page.getByTestId("task-card").filter({ hasText: "loop-diuretic" });
  await expect(diuretic).toHaveAttribute("data-status", "open");
  await page.getByTestId("demo-clock").getByRole("button", { name: "Advance to Monday 14:00" }).click();
  // Loading the feed file and re-scoring takes a few seconds.
  await expect(page.getByTestId("demo-clock-time")).toHaveText(/Mon 9 Nov.*14:00/, { timeout: 30_000 });
  await expect(diuretic).toHaveAttribute("data-status", "done");
  await expect(diuretic).toContainText("Resolved by data: Furosemide 80 mg filled 2026-11-09");
  await page.screenshot({ path: "screenshots/demo-task-green.png", fullPage: true });

  expect(Date.now() - started).toBeLessThan(180_000);
});
