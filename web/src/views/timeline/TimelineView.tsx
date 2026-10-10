import { useEffect, useMemo } from "react";
import { query } from "../../api/client";
import { updateState } from "../../state/store";
import { QueryView } from "../../components/query/QueryView";
import { useViewState } from "../../hooks/useViewState";
import type { MessagesResponse } from "../../api/types/data";
import type { FunctionSummaryRow, TimelineResponse } from "../../api/types/execution";
import { executionLocations } from "../executionState";
import { TimelinePanel, type TimelineData } from "./TimelinePanel";

export function TimelineView() {
  const state = useViewState();
  const locations = useMemo(
    () => executionLocations(state),
    [state.meta.locations, state.locations],
  );
  const detailLocation =
    state.detailLocation && !state.locations.has(state.detailLocation)
      ? null
      : state.detailLocation;
  const visible = useMemo(
    () =>
      detailLocation != null
        ? [detailLocation]
        : locations.slice(state.timelinePage * 24, (state.timelinePage + 1) * 24),
    [detailLocation, locations, state.timelinePage],
  );
  useEffect(() => {
    if (state.detailLocation !== detailLocation) {
      updateState((previous) =>
        previous.detailLocation === state.detailLocation ? { detailLocation } : {},
      );
    }
  }, [state.detailLocation, detailLocation]);
  return (
    <QueryView<TimelineData>
      queryKey={[state.epoch]}
      load={(signal) =>
        Promise.all([
          query<TimelineResponse>(
            "timeline",
            {
              locations: visible.join(",") || "__none__",
              detail: detailLocation != null ? "1" : "0",
              bins: 1200,
            },
            signal,
            state,
          ),
          query<readonly FunctionSummaryRow[]>("summary", {}, signal, state),
          query<MessagesResponse>("messages", {}, signal, state),
        ])
      }
      render={(result) => (
        <TimelinePanel
          result={result}
          state={state}
          locations={locations}
          visible={visible}
          detailLocation={detailLocation}
        />
      )}
    />
  );
}
