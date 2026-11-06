import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

test.describe.configure({ mode: "serial" });

test("maria: Raymond first, duplicate confirmed, furosemide conflict appears", async ({ page }) => {
  await signIn(page, "maria");

  const first = page.getByTestId("queue-row").first();
  await expect(first).toHaveAttribute("data-member", "SYN-001");
  await expect(first.getByTestId("why-chip")).toHaveCount(3);
  await expect(first.getByTestId("why-chip").first()).toHaveText(
    "Furosemide ran out 2026-10-30; no fill since discharge",
  );
  await expect(first.getByTestId("duplicate-badge")).toHaveText("Possible duplicate · flagged by data layer");
  await first.getByTestId("score").hover();
  await expect(first.getByTestId("score-explain")).toHaveText(
    "Risk .88 x40 + Urgency 1.0 x30 + Fixable 1.0 x20 + Reach .82 x10 = 93.4",
  );
  await page.screenshot({ path: "screenshots/queue.png", fullPage: true });

  await first.getByRole("link", { name: "Open Raymond Tull" }).click();
  await page.waitForURL("**/members/SYN-001");
  const banner = page.getByTestId("match-banner");
  await expect(banner).toContainText("Possible duplicate · flagged by data layer");
  await expect(banner).toContainText("SYN-001-H");
  await expect(page.getByTestId("reach-ladder")).toContainText("Joan Tull");
  await expect(page.getByTestId("reach-ladder").locator("li").nth(1)).toContainText("555-0143");

  // The hospital's 80 mg list belongs to SYN-001-H, so its conflict appears once a person confirms.
  await banner.getByRole("button", { name: /Same person: confirm/ }).click();
  await expect(page.getByTestId("match-banner")).toHaveCount(0);
  const conflict = page.getByTestId("conflict-card");
  await expect(conflict).toContainText("furosemide");
  await expect(conflict).toContainText("PBM: 40 mg");
  await expect(conflict).toContainText("Hospital document: 80 mg");
  await expect(conflict).toContainText("flagged by data layer");
  await page.screenshot({ path: "screenshots/member-360.png", fullPage: true });
});

test("alma: Kayla's Part 2 records are restricted until revealed with a reason", async ({ page }) => {
  await signIn(page, "alma");
  await page.getByRole("link", { name: "Open Kayla Morrison" }).click();
  await page.waitForURL("**/members/SYN-004");

  const panel = page.getByTestId("part2-panel");
  await expect(panel).toContainText("Records restricted");
  await expect(panel).not.toContainText("counselling session");

  await panel.getByRole("button", { name: "Reveal restricted records" }).click();
  await panel.getByLabel(/Reason/).fill("Coordinate MOUD and follow-up after psychiatric discharge");
  await panel.getByRole("button", { name: "Reveal (audited)" }).click();

  const notes = page.getByTestId("part2-notes");
  await expect(notes).toContainText("42 CFR Part 2");
  await expect(notes.locator("li")).toHaveCount(3);
  await expect(notes).toContainText("New Dawn Recovery");
  await page.screenshot({ path: "screenshots/member-360-part2.png", fullPage: true });
});

test("maria completes Raymond's call end to end; the queue then shows him as T2", async ({ page }) => {
  await signIn(page, "maria");
  await page.getByRole("link", { name: "Open Raymond Tull" }).click();
  await page.waitForURL("**/members/SYN-001");
  await expect(page.getByTestId("match-banner")).toHaveCount(0); // confirmed in the previous test
  await page.getByRole("link", { name: "Start call" }).click();
  await page.waitForURL("**/members/SYN-001/call");

  // Pre-call
  const pre = page.getByTestId("pre-call");
  await expect(page.getByTestId("call-summary")).toContainText("555-0142");
  await expect(page.getByTestId("voicemail-script")).not.toContainText(/furosemide|heart|discharge/i);
  await pre.getByRole("button", { name: /Dial 555-0142/ }).click();

  // Live: identity before any health detail
  const live = page.getByTestId("live-pane");
  await expect(live).toContainText("connected");
  await expect(live.getByLabel("Nurse notes")).toHaveCount(0);
  await live.getByRole("button", { name: "Name and date of birth verified" }).click();
  await live.getByLabel("Member agreed to transcription").check();
  await live.getByLabel("Nurse notes").fill("Spoke with Raymond and Joan. Has 2 days of furosemide 40 mg left.");
  await live.getByRole("button", { name: "Go to wrap-up" }).click();

  // Wrap-up
  const wrap = page.getByTestId("wrap-pane");
  await expect(page.getByTestId("field-counts")).toHaveText("22 to confirm · 8 to re-ask · 10 live only");
  const highRisk = wrap.getByTestId("high-risk-field");
  await expect(highRisk).toHaveCount(6);
  for (let i = 0; i < 6; i++) {
    const field = highRisk.nth(i);
    await field.getByRole("button", { name: /^Confirm / }).click();
    await expect(field).toContainText("Confirmed one by one");
  }
  await wrap.getByRole("button", { name: "Confirm 16 low-risk fields" }).click();
  await expect(wrap.getByRole("button", { name: "All 16 low-risk fields confirmed" })).toBeVisible();
  await wrap.getByRole("button", { name: "End call and create tasks" }).click();
  const tasks = page.getByTestId("task-list");
  await expect(tasks).toContainText("Message prescriber");
  await expect(tasks).toContainText("Track coverage request");
  await expect(tasks).toContainText("Re-query HIE");
  await page.screenshot({ path: "screenshots/call-wrap-up.png", fullPage: true });
  await wrap.getByRole("button", { name: "Save to record" }).click();

  // Back on the queue, Raymond has re-ranked
  await page.waitForURL("**/queue");
  const raymond = page.locator('[data-testid="queue-row"][data-member="SYN-001"]');
  await expect(raymond).toContainText("T2");
  await expect(page.getByTestId("queue-row").first()).not.toHaveAttribute("data-member", "SYN-001");
});
