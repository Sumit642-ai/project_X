// Keyboard-only: Raymond's call from sign-in to save, with Tab, Enter, Space and typing only.
// No mouse clicks and no programmatic focus: every control is reached by tabbing to it.
import { expect, test, type Locator, type Page } from "@playwright/test";

import { resetDemo } from "./helpers";

test.describe.configure({ mode: "serial" });
test.beforeEach(async ({ request }) => resetDemo(request));
test.afterEach(async ({ request }) => resetDemo(request));

const MAX_TABS = 250;

/** Press Tab until `target` has focus (fails if it is not reachable by keyboard). */
async function tabTo(page: Page, target: Locator): Promise<void> {
  await expect(target).toBeVisible();
  for (let i = 0; i < MAX_TABS; i += 1) {
    if (await target.evaluate((el) => el === document.activeElement)) {
      const ring = await target.evaluate((el) => {
        const style = getComputedStyle(el);
        return style.outlineStyle !== "none" || style.boxShadow !== "none";
      });
      expect(ring, "focused control shows a focus indicator").toBe(true);
      return;
    }
    await page.keyboard.press("Tab");
  }
  throw new Error(`not reachable with Tab: ${target.toString()}`);
}

async function activate(page: Page, target: Locator, key: "Enter" | "Space" = "Enter"): Promise<void> {
  await tabTo(page, target);
  await page.keyboard.press(key);
}

test("Raymond's call can be completed with the keyboard alone", async ({ page }) => {
  test.setTimeout(150_000);
  await page.goto("/login");
  await activate(page, page.getByRole("button", { name: /Sign in as Maria/ }));
  await page.waitForURL("**/queue");

  await activate(page, page.getByRole("link", { name: "Open Raymond Tull" }));
  await page.waitForURL("**/members/SYN-001");
  await activate(page, page.getByTestId("match-banner").getByRole("button", { name: "Same person: confirm" }));
  await expect(page.getByTestId("match-banner")).toHaveCount(0);

  await activate(page, page.getByRole("link", { name: "Start call" }));
  await page.waitForURL("**/members/SYN-001/call");
  await activate(page, page.getByTestId("pre-call").getByRole("button", { name: /Dial 555-0142/ }));

  const live = page.getByTestId("live-pane");
  await activate(page, live.getByRole("button", { name: "Name and date of birth verified" }));
  await activate(page, live.getByLabel("Member agreed to transcription"), "Space");
  await expect(live.getByLabel("Member agreed to transcription")).toBeChecked();
  await tabTo(page, live.getByLabel("Nurse notes"));
  await page.keyboard.type("Spoke with Raymond and Joan by phone. No furosemide at home.");
  await activate(page, live.getByRole("button", { name: "Go to wrap-up" }));

  const wrap = page.getByTestId("wrap-pane");
  const highRisk = wrap.getByTestId("high-risk-field");
  await expect(highRisk).toHaveCount(6);
  for (let i = 0; i < 6; i += 1) {
    await activate(page, highRisk.nth(i).getByRole("button", { name: /^Confirm / }));
    await expect(highRisk.nth(i)).toContainText("Confirmed one by one");
  }
  await activate(page, wrap.getByRole("button", { name: "Confirm 16 low-risk fields" }));
  await expect(wrap.getByRole("button", { name: "All 16 low-risk fields confirmed" })).toBeVisible();
  await activate(page, wrap.getByRole("button", { name: "End call and create tasks" }));
  await expect(page.getByTestId("task-list")).toContainText("Message prescriber");
  await activate(page, wrap.getByRole("button", { name: "Save to record" }));

  await page.waitForURL("**/queue");
  await expect(page.locator('[data-testid="queue-row"][data-member="SYN-001"]')).toContainText("T2");
});
