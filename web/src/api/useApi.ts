import { useMemo } from "react";
import { hashKey, useQuery, type QueryKey } from "@tanstack/react-query";
import { queryKeys } from "./queryKeys";
import { queryFn } from "./queryFn";
import type { ApiParams } from "./types/common";

export type QueryResult<Data> =
  | { status: "loading"; started: number }
  | { status: "ready"; data: Data; started: number }
  | { status: "error"; error: Error; started: number };
export type QueryLoader<Data> = (signal: AbortSignal) => Promise<Data>;
type ApiRequest<Data> =
  | [endpoint: string, params: ApiParams, enabled?: boolean]
  | [load: QueryLoader<Data>, queryKey: QueryKey, enabled?: boolean];

function isEndpointRequest<Data>(
  request: ApiRequest<Data>,
): request is [string, ApiParams, boolean?] {
  return typeof request[0] === "string";
}

export function useApi<Data>(
  endpoint: string,
  params: ApiParams,
  enabled?: boolean,
): QueryResult<Data>;
export function useApi<Data>(
  load: QueryLoader<Data>,
  key: QueryKey,
  enabled?: boolean,
): QueryResult<Data>;
export function useApi<Data>(...request: ApiRequest<Data>): QueryResult<Data> {
  let queryKey: QueryKey;
  let load: QueryLoader<Data>;
  if (isEndpointRequest(request)) {
    const key = queryKeys.request(request[0], request[1]);
    queryKey = key;
    load = (signal) => queryFn<Data>({ queryKey: key, signal });
  } else {
    [load, queryKey] = request;
  }
  const queryHash = hashKey(queryKey);
  const timing = useMemo(() => ({ started: performance.now() }), [queryHash]);
  const result = useQuery<Data, Error>({
    queryKey,
    queryHash,
    enabled: request[2] ?? true,
    queryFn: ({ signal }) => {
      timing.started = performance.now();
      return load(signal);
    },
  });
  if (result.status === "error")
    return { status: "error", error: result.error, started: timing.started };
  if (result.status === "success")
    return { status: "ready", data: result.data, started: timing.started };
  return { status: "loading", started: timing.started };
}
