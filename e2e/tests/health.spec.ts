import { expect, test } from "@playwright/test";

test("sign-in page shows ok from the backend /health endpoint", async ({ page }) => {
  await page.goto("/login");

  await expect(page.getByTestId("health-status")).toHaveText("ok");
});
