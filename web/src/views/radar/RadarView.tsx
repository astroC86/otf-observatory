import { useEffect, useMemo } from "react";
import { scope } from "../../api/client";
import { updateState } from "../../state/store";
import { QueryView } from "../../components/query/QueryView";
import { useViewState } from "../../hooks/useViewState";
import type { OverviewResponse } from "../../api/types/execution";
import { executionLocations } from "../executionState";
import { RadarPanel } from "./RadarPanel";

export function RadarView() {
  const state = useViewState();
  const group =
    state.radarGroup ?? (state.meta.regions.some((region) => region.group === "MPI") ? "MPI" : "");
  const allLocations = useMemo(
    () => executionLocations(state),
    [state.meta.locations, state.locations],
  );
  const page = Math.min(state.radarPage || 0, Math.max(0, Math.ceil(allLocations.length / 32) - 1));
  const locations = useMemo(
    () => allLocations.slice(page * 32, (page + 1) * 32),
    [allLocations, page],
  );
  useEffect(() => {
    if (state.radarPage !== page) {
      updateState((previous) =>
        previous.radarPage === state.radarPage ? { radarPage: page } : {},
      );
    }
  }, [state.radarPage, page]);
  return (
    <QueryView<OverviewResponse>
      endpoint="overview"
      params={scope(
        {
          by: "location",
          bins: 250,
          group,
          locations: locations.join(",") || "__none__",
        },
        state,
      )}
      render={(data) => (
        <RadarPanel
          data={data}
          locations={locations}
          total={allLocations.length}
          page={page}
          group={group}
          state={state}
        />
      )}
    />
  );
}
