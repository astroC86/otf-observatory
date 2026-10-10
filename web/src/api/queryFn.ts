import type { QueryFunctionContext } from "@tanstack/react-query";
import { api } from "./client";
import type { RequestKey } from "./queryKeys";
export function queryFn<Data>({
  queryKey,
  signal,
}: Pick<QueryFunctionContext<RequestKey>, "queryKey" | "signal">): Promise<Data> {
  const [, path, params, body] = queryKey;
  const payload: unknown = body ? JSON.parse(body) : undefined;
  return api<Data>(path, Object.fromEntries(params), payload, signal);
}
