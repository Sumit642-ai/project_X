import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { chromium, expect, test } from "@playwright/test";
import lighthouse from "lighthouse";

const PORT = 9333;
const BASE = "http://127.0.0.1:5174";

// Lighthouse drives the same browser profile Playwright signed into, so the page has data.
test("Lighthouse accessibility is 90+ on the queue and the member 360", async () => {
  const profile = mkdtempSync(join(tmpdir(), "cc-lh-"));
  const context = await chromium.launchPersistentContext(profile, {
    args: [`--remote-debugging-port=${PORT}`],
    viewport: { width: 1440, height: 1000 },
  });
  try {
    const page = context.pages()[0] ?? (await context.newPage());
    await page.goto(`${BASE}/login`);
    await page.getByRole("button", { name: /Sign in as Maria/ }).click();
    await page.waitForURL("**/queue");

    const scores: Record<string, number> = {};
    for (const path of ["/queue", "/members/SYN-001"]) {
      const result = await lighthouse(`${BASE}${path}`, {
        port: PORT,
        output: "json",
        logLevel: "error",
        onlyCategories: ["accessibility"],
        disableStorageReset: true,
      });
      // Guard against auditing the sign-in page after a redirect.
      const audited = new URL(result?.lhr.finalDisplayedUrl ?? "").pathname;
      expect(audited).toBe(path);
      const category = result?.lhr.categories.accessibility;
      scores[path] = Math.round((category?.score ?? 0) * 100);
      const failing = Object.values(result?.lhr.audits ?? {})
        .filter((a) => a.score !== null && a.score < 1 && a.scoreDisplayMode === "binary")
        .map((a) => a.id);
      console.log(`Lighthouse accessibility ${audited}: ${scores[path]}${failing.length ? ` (failing: ${failing.join(", ")})` : ""}`);
    }
    writeFileSync("screenshots/lighthouse-accessibility.json", JSON.stringify(scores, null, 2));
    for (const score of Object.values(scores)) expect(score).toBeGreaterThanOrEqual(90);
  } finally {
    await context.close();
  }
});
