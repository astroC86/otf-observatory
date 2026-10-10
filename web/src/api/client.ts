import { getState } from "../state/store";
import type { AppState } from "../state/types";
import type { ApiParams } from "./types/common";
import { normalizeMetadata } from "./normalizeMetadata";

export async function api<T>(
  path: string,
  params: ApiParams = {},
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const search = new URLSearchParams(
    Object.entries(params).map(([key, value]) => [key, String(value)]),
  );
  const response = await fetch("/api/" + path + (search.size ? "?" + search : ""), {
    ...(body
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      : {}),
    ...(signal ? { signal } : {}),
  });
  const data: unknown = await response.json();
  if (!response.ok) {
    const message = data && typeof data === "object" && "error" in data ? data.error : null;
    throw Error(message ? String(message) : `HTTP ${response.status}`);
  }
  // The server owns endpoint schemas; normalize its optional metadata collections
  // once, so renderers receive the same non-nullable shape for every archive.
  return (path === "meta" ? normalizeMetadata(data) : data) as T;
}
export function scope(extra: ApiParams = {}, snapshot: Readonly<AppState> = getState()): ApiParams {
  const chosen =
    snapshot.locations.size === snapshot.meta?.locations.length
      ? ""
      : snapshot.locations.size
        ? [...snapshot.locations].join(",")
        : "__none__";
  return {
    id: snapshot.id,
    start: snapshot.start,
    end: snapshot.end,
    locations: chosen,
    region: snapshot.region,
    exclude: snapshot.exclude,
    group: snapshot.group,
    ...extra,
  };
}
export function query<T>(
  path: string,
  extra: ApiParams = {},
  signal?: AbortSignal,
  snapshot: Readonly<AppState> = getState(),
): Promise<T> {
  return api<T>(path, scope(extra, snapshot), undefined, signal);
}
export async function uploadFile(token: string, file: File): Promise<void> {
  const response = await fetch(
    "/api/upload/file?" + new URLSearchParams({ token, path: file.webkitRelativePath }),
    { method: "POST", body: file },
  );
  if (!response.ok) {
    const data: unknown = await response.json();
    throw Error(
      data && typeof data === "object" && "error" in data
        ? String(data.error)
        : `HTTP ${response.status}`,
    );
  }
}
