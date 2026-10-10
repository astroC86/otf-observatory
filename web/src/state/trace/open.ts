import { QueryObserver } from "@tanstack/react-query";
import { api } from "../../api/client";
import { mutate } from "../../api/mutate";
import { queryClient } from "../../api/queryClient";
import { queryFn } from "../../api/queryFn";
import { queryKeys, type RequestKey } from "../../api/queryKeys";
import type { ImportJob, TraceListing } from "../../api/types/common";
import type { SavedSession } from "../types";
import { updateUi } from "../store";
import { num } from "../../lib/format/numbers";
import {
  beginTraceLoad,
  currentTraceLoad,
  isCurrentTraceLoad,
  getLoadingId,
  setLoadingId,
} from "./requests";
import { loadTrace } from "./load";

export async function openDialog(): Promise<void> {
  const traces = await api<TraceListing[]>("traces");
  updateUi({ traces, openError: null, dialog: "open" });
}
export async function openTrace(
  data: { id?: string; path?: string },
  restore: SavedSession | null = null,
  request = beginTraceLoad(),
): Promise<void> {
  try {
    const job = await mutate<ImportJob>("open", data);
    if (!isCurrentTraceLoad(request)) return;
    setLoadingId(job.id);
    updateUi({ dialog: null });
    if (job.state !== "ready") {
      updateUi({ dialog: "loading" });
      await waitImport(job.id, request);
    }
    if (!isCurrentTraceLoad(request)) return;
    await loadTrace(job.id, restore, request);
  } catch (error) {
    if (!isCurrentTraceLoad(request)) return;
    updateUi({
      openError: error instanceof Error ? error.message : String(error),
      dialog: "open",
    });
  }
}
export function waitImport(id: string, request: number | null = null): Promise<void> {
  if (request !== null && !isCurrentTraceLoad(request)) return Promise.resolve();
  return new Promise<void>((resolve, reject) => {
    const observer = new QueryObserver<ImportJob, Error, ImportJob, ImportJob, RequestKey>(
      queryClient,
      {
        queryKey: queryKeys.status(id),
        queryFn: queryFn<ImportJob>,
        staleTime: 0,
        retry: false,
        refetchOnMount: "always",
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
        refetchIntervalInBackground: true,
        refetchInterval: (query) => {
          const state = query.state.data?.state;
          return state === "ready" || state === "error" ? false : 650;
        },
      },
    );
    observer.subscribe((result) => {
      if (request !== null && !isCurrentTraceLoad(request)) {
        observer.destroy();
        resolve();
        return;
      }
      // A previous import may have cached status for this id. Wait for this
      // observer's status request rather than treating stale cached data as final.
      if (result.isFetching) return;
      if (result.isError) {
        observer.destroy();
        reject(result.error);
        return;
      }
      if (!result.isSuccess) return;
      const job = result.data;
      if (job.state === "ready") {
        observer.destroy();
        if (getLoadingId() === id) updateUi({ dialog: null });
        resolve();
      } else if (job.state === "error") {
        observer.destroy();
        reject(Error(job.error));
      } else {
        updateUi({
          loadingPhase: job.phase,
          loadingCount: job.events ? `${num(job.events, 0)} events indexed` : "",
        });
      }
    });
  });
}
export async function cancelImport(): Promise<void> {
  const id = getLoadingId(),
    request = currentTraceLoad();
  await mutate("cancel", { id });
  if (isCurrentTraceLoad(request) && getLoadingId() === id)
    updateUi({ loadingPhase: "Cancelling…" });
}
