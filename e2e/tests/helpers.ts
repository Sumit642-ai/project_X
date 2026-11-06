import type { APIRequestContext, Page } from "@playwright/test";

export const NAMES: Record<string, string> = { maria: "Maria", alma: "Alma", janet: "Janet" };

export async function signIn(page: Page, username: string): Promise<void> {
  await page.goto("/login");
  await page.getByRole("button", { name: new RegExp(`Sign in as ${NAMES[username] ?? username}`) }).click();
  await page.waitForURL("**/queue");
}

/** Back to the pristine demo data (Monday 08:00). Uses the API, so it works after a failure. */
export async function resetDemo(request: APIRequestContext): Promise<void> {
  const login = await request.post("/api/auth/login", { data: { username: "janet" } });
  const { access_token: token } = (await login.json()) as { access_token: string };
  await request.post("/api/demo/clock/reset", { headers: { Authorization: `Bearer ${token}` } });
}
