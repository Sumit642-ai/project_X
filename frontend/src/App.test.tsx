import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";

import { AppRoutes } from "./App";
import { AuthProvider } from "./lib/auth";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

function stubBackend(demoMode: boolean) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string) => {
      const body = url.endsWith("/demo/config")
        ? { demo_mode: demoMode, users: demoMode ? [{ username: "maria", label: "Maria · RN, complex case management" }] : [] }
        : { status: "ok" };
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    }),
  );
}

function renderAt(path: string) {
  render(
    <AuthProvider>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </AuthProvider>,
  );
}

test("in demo mode the sign-in page lists the seeded users and the API status", async () => {
  stubBackend(true);
  renderAt("/queue");
  expect(await screen.findByRole("button", { name: /Sign in as Maria/ })).toBeInTheDocument();
  expect(await screen.findByTestId("health-status")).toHaveTextContent("ok");
  expect(screen.getByRole("link", { name: /old way/ })).toHaveAttribute("href", "/demo/old-way");
});

test("outside demo mode no users are listed: sign in by username", async () => {
  stubBackend(false);
  renderAt("/login");
  expect(await screen.findByLabelText("Username")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Sign in as/ })).toBeNull();
});

test("the old-way page shows seven portal tabs with Raymond's scattered data", async () => {
  stubBackend(true);
  renderAt("/demo/old-way");
  const tabs = await screen.findAllByRole("tab");
  expect(tabs).toHaveLength(7);
  fireEvent.click(screen.getByRole("tab", { name: /HIE viewer/ }));
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Furosemide 80 mg daily");
});
