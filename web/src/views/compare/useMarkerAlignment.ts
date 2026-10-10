import { useMutation } from "@tanstack/react-query";
import { api } from "../../api/client";
import { getState } from "../../state/store";
import { notify } from "../../state/uiActions";
import { updateQuery } from "../shared/dataControls";
import { captureMarkerInputs, markerIds, preserveMarkerWindow } from "./actions";
import { openRuns } from "./requests";
import type { MarkerResult, MarkerSession } from "./types";

export function useMarkerAlignment() {
  return useMutation({
    mutationFn: async (mode: "align" | "manual" | "reset") => {
      captureMarkerInputs();
      const state = getState(),
        baseline = state.id || "",
        ids = markerIds(state);
      const runs = ids.map((id) => {
        const { time, offset, marker, location } = state.markerInputs[id]!;
        return {
          id,
          time,
          offset,
          ...(marker != null ? { marker } : {}),
          ...(location != null ? { location } : {}),
        };
      });
      await openRuns(ids);
      let next: MarkerSession;
      if (mode === "align")
        next = await api<MarkerSession>("align-markers", {}, { baseline, runs });
      else {
        const preview = await api<MarkerResult>(
          "compare-offsets",
          {},
          {
            baseline,
            runs: runs.map((run) => ({ ...run, offset: mode === "reset" ? 0 : run.offset })),
          },
        );
        next = {
          baseline,
          method: "manual-translation",
          target: null,
          runs: preview.runs.map(({ id, name, offset, fullRange }) => ({
            id,
            name,
            offset,
            time: Number(getState().markerInputs[id]?.time ?? 0),
            range: fullRange,
          })),
          range: {
            start: Math.min(...preview.runs.map((run) => run.fullRange.start)),
            end: Math.max(...preview.runs.map((run) => run.fullRange.end)),
          },
        };
      }
      if (getState().id !== baseline || markerIds(getState()).join() !== ids.join()) return;
      const markerInputs = { ...getState().markerInputs };
      for (const run of next.runs)
        markerInputs[run.id] = { ...markerInputs[run.id]!, offset: run.offset };
      updateQuery({
        markerWindow: preserveMarkerWindow(next.range),
        markerSession: next,
        markerInputs,
      });
    },
    onError: (error: Error) => notify(error.message),
  });
}
