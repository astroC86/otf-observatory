import { queryClient } from "./queryClient";
import { api } from "./client";
export function mutate<Data>(path: string, body: unknown): Promise<Data> {
  return queryClient
    .getMutationCache()
    .build<Data, Error, unknown, unknown>(queryClient, {
      mutationKey: ["trace-action", path],
      mutationFn: (value) => api<Data>(path, {}, value),
    })
    .execute(body);
}
