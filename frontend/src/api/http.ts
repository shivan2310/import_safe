import type { Api } from "./index";
import { ApiError } from "./errors";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init.headers },
    });
  } catch {
    throw new ApiError("Could not reach the ImportSafe server.", 0);
  }
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    let code: string | null = null;
    try {
      const detail = (await res.json())?.detail;
      if (typeof detail === "string") message = detail;
      else if (detail?.message) {
        message = detail.message;
        code = detail.code ?? null;
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(message, res.status, {
      code,
      errorId: res.headers.get("x-request-id") ?? undefined,
    });
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

const enc = encodeURIComponent;

export const httpApi: Api = {
  create: (req) => request("/api/investigations", { method: "POST", body: JSON.stringify(req) }),
  get: (id) => request(`/api/investigations/${enc(id)}`),
  list: () => request("/api/investigations"),
  answer: (id, body) =>
    request(`/api/investigations/${enc(id)}/answers`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  cancel: (id) => request(`/api/investigations/${enc(id)}/cancel`, { method: "POST" }),
  remove: (id) => request(`/api/investigations/${enc(id)}`, { method: "DELETE" }),
  patchAssumptions: (id, overrides) =>
    request(`/api/investigations/${enc(id)}/assumptions`, {
      method: "PATCH",
      body: JSON.stringify({ overrides }),
    }),
  report: (id) => request(`/api/investigations/${enc(id)}/report`),
};
