import type { Page } from "@playwright/test";

export const NAMES: Record<string, string> = { maria: "Maria", alma: "Alma", janet: "Janet" };

export async function signIn(page: Page, username: string): Promise<void> {
  await page.goto("/login");
  await page.getByRole("button", { name: new RegExp(`Sign in as ${NAMES[username] ?? username}`) }).click();
  await page.waitForURL("**/queue");
}
