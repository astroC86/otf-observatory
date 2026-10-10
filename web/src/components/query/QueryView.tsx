import { Fragment, useLayoutEffect, type ReactNode } from "react";
import type { QueryKey } from "@tanstack/react-query";
import { useApi, type QueryLoader } from "../../api/useApi";
import { queryFn } from "../../api/queryFn";
import { queryKeys } from "../../api/queryKeys";
import type { ApiParams } from "../../api/types/common";
import { queryClient } from "../../api/queryClient";
import type { ViewState } from "../../state/types";
import { finishRender } from "../../state/viewActions";
import { useViewState } from "../../hooks/useViewState";
import { MetricOverlay } from "../../views/metrics/MetricOverlay";
import { EmptyState } from "../ui/EmptyState";

export type QueryViewProps<Data> = { render: (data: Data) => ReactNode } & (
  | { endpoint: string; params: ApiParams; load?: never; queryKey?: never }
  | {
      load: QueryLoader<Data>;
      queryKey: QueryKey;
      endpoint?: never;
      params?: never;
    }
);
const startTimes = new WeakMap<ViewState, number>();

export function QueryView<Data>({ render, ...props }: QueryViewProps<Data>) {
  const snapshot = useViewState();
  let started = startTimes.get(snapshot);
  const firstAttempt = started === undefined;
  if (started === undefined) {
    started = performance.now();
    startTimes.set(snapshot, started);
  }
  let queryKey: QueryKey;
  let load: QueryLoader<Data>;
  if (props.load) {
    load = props.load;
    // A presentation-only epoch must never identify a server request.
    queryKey =
      props.queryKey.length === 1 && typeof props.queryKey[0] === "number"
        ? queryKeys.view(snapshot)
        : props.queryKey;
  } else {
    const key = queryKeys.request(props.endpoint, props.params);
    queryKey = key;
    load = (signal) => queryFn<Data>({ queryKey: key, signal });
  }
  // A suspended retry must expose its failure instead of retrying on every mount.
  const failed = !firstAttempt && queryClient.getQueryState(queryKey)?.status === "error";
  const result = useApi<Data>(load, queryKey, !failed);
  const error = result.status === "error" ? result.error : undefined;
  useLayoutEffect(() => {
    if (result.status !== "loading") finishRender(snapshot.epoch, started, error);
  }, [snapshot.epoch, started, result.status, error]);
  if (result.status === "loading") {
    // Suspending a deferred update retains the mounted view, not a remounted copy.
    throw queryClient.fetchQuery({
      queryKey,
      queryFn: ({ signal }) => load(signal),
    });
  }
  if (result.status === "error")
    return <EmptyState title="Unable to render this view" detail={result.error.message} />;
  const overlay =
    snapshot.view === "radar"
      ? "radar"
      : snapshot.view === "timeline" || snapshot.view === "counters"
        ? "line"
        : null;
  return (
    <Fragment>
      {overlay ? <MetricOverlay mode={overlay} snapshot={snapshot} /> : null}
      {render(result.data)}
    </Fragment>
  );
}
