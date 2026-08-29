/**
 * HTTP client.
 *
 * A thin fetch wrapper, not a generated SDK: the API surface is small enough
 * that hand-written functions stay more readable than codegen. Every function
 * throws `ApiError` on a non-2xx response, carrying the Persian message the
 * backend already produced (see `backend/app/api/errors.py`) so callers never
 * need to translate an error themselves.
 */

import type { ApiErrorBody } from "./types";

export class ApiError extends Error {
  code: string;
  hint?: string;
  details?: Record<string, unknown>;
  status: number;

  constructor(status: number, body: ApiErrorBody) {
    super(body.error.message);
    this.status = status;
    this.code = body.error.code;
    this.hint = body.error.hint;
    this.details = body.error.details;
  }
}

const BASE = "/api";

async function request<T>(
  path: string,
  init?: RequestInit & { params?: Record<string, string | number | boolean | undefined> },
): Promise<T> {
  const url = new URL(`${BASE}${path}`, window.location.origin);
  if (init?.params) {
    for (const [key, value] of Object.entries(init.params)) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
  }

  const response = await fetch(url.toString().replace(window.location.origin, ""), {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let body: ApiErrorBody;
    try {
      body = await response.json();
    } catch {
      body = {
        error: {
          code: "unknown_error",
          message: "خطای ناشناخته‌ای رخ داد.",
        },
      };
    }
    throw new ApiError(response.status, body);
  }

  if (response.status === 204) return undefined as T;

  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json() as Promise<T>;
  }
  return response.text() as unknown as Promise<T>;
}

export const api = {
  get: <T>(path: string, params?: Record<string, string | number | boolean | undefined>) =>
    request<T>(path, { method: "GET", params }),

  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),

  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),

  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),

  delete: <T>(path: string, params?: Record<string, string | number | boolean | undefined>) =>
    request<T>(path, { method: "DELETE", params }),

  /** Multipart upload; used for the file-upload fallback when the picker cannot resolve a local path. */
  upload: <T>(path: string, file: File, params?: Record<string, string>) => {
    const form = new FormData();
    form.append("file", file);
    const url = new URL(`${BASE}${path}`, window.location.origin);
    if (params) for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
    return fetch(url.toString().replace(window.location.origin, ""), {
      method: "POST",
      body: form,
    }).then(async (response) => {
      if (!response.ok) {
        const body = (await response.json()) as ApiErrorBody;
        throw new ApiError(response.status, body);
      }
      return response.json() as Promise<T>;
    });
  },
};

/** URL for streaming/downloading an asset directly (video player src, downloads). */
export function assetUrl(assetId: string): string {
  return `${BASE}/files/${assetId}`;
}

export function assetDownloadUrl(assetId: string): string {
  return `${BASE}/files/${assetId}/download`;
}
