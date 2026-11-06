const TOKEN_KEY = "casecompass.token";

export class ApiError extends Error {
  constructor(
    public status: number,
    public reason: string,
    public detail: unknown = null,
  ) {
    super(reason);
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

function reasonFrom(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "reason" in detail) {
    return String((detail as { reason: unknown }).reason);
  }
  return `request failed (HTTP ${status})`;
}

// Same-origin "/api" by default (Vite proxy in development, a rewrite on Vercel). For a backend
// deployed separately, build with VITE_API_BASE_URL=https://your-backend.example.
export const API_BASE = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/+$/, "");

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`${API_BASE}${path}`, {
    method: init.method ?? "GET",
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  const text = await response.text();
  const body: unknown = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new ApiError(response.status, reasonFrom(body, response.status), (body as { detail?: unknown } | null)?.detail ?? null);
  }
  return body as T;
}
