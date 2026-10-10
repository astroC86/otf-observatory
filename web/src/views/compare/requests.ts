import { api, scope } from "../../api/client";
import type { ImportJob, TraceListing } from "../../api/types/common";
import type { ViewState } from "../../state/types";
import { waitImport } from "../../state/trace/open";
import { markerIds } from "./actions";
import type { ComparisonData, ComparisonResult, MarkerResult, ProfilesResult } from "./types";

export async function openRuns(ids: readonly string[], signal?: AbortSignal) {
  await Promise.all(
    ids.map(async (id) => {
      const opened = await api<ImportJob>("open", {}, { id }, signal);
      if (opened.state !== "ready") await waitImport(id);
    }),
  );
}

async function resultOf<T>(request: Promise<T>) {
  try {
    return { data: await request, error: "" };
  } catch (error) {
    return { data: null, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function loadComparison(
  state: ViewState,
  signal: AbortSignal,
): Promise<ComparisonData> {
  const send = <T>(path: string, body: unknown) => api<T>(path, {}, body, signal);
  const archives = await api<TraceListing[]>("traces", {}, undefined, signal);
  const ids = markerIds(state),
    selection = scope({}, state);
  const markerSession =
    state.markerSession?.baseline === state.id &&
    state.markerSession.runs.map((run) => run.id).join() === ids.join()
      ? state.markerSession
      : null;
  const marker = await resultOf(
    markerSession
      ? openRuns(ids, signal).then(() =>
          send<MarkerResult>("compare-offsets", {
            baseline: state.id,
            runs: markerSession.runs.map((run) => ({
              id: run.id,
              offset: run.offset,
              location: state.markerInputs[run.id]?.location,
            })),
            displayStart: state.markerWindow?.start ?? markerSession.range.start,
            displayEnd: state.markerWindow?.end ?? markerSession.range.end,
            region: state.region,
            exclude: state.exclude,
            group: state.group,
            profileSelectedLocation: state.markerSelectedLocationOnly,
            bins: 600,
          }),
        )
      : Promise.resolve(null),
  );
  const other = archives.find((trace) => trace.id === state.comparison);
  const ensemble = state.ensemble?.baseline.id === state.id ? state.ensemble : null;
  const [comparison, profiles] = await Promise.all([
    resultOf(
      other?.loaded
        ? send<ComparisonResult>("compare", {
            ...selection,
            other: other.id,
            shift: state.shift || 0,
            scale: state.alignmentScale || 1,
            anchors:
              state.alignmentApplied && state.alignmentMode === "piecewise"
                ? state.alignment?.piecewise
                : null,
          })
        : Promise.resolve(null),
    ),
    resultOf(
      ensemble && state.ensembleApplied
        ? send<ProfilesResult>("compare-many", {
            ...selection,
            mappings: ensemble.runs.map((run) => ({
              id: run.id,
              shift: run.alignment.shift,
              scale: run.alignment.scale,
              anchors: state.ensembleMode === "piecewise" ? run.alignment.piecewise : null,
            })),
          })
        : Promise.resolve(null),
    ),
  ]);
  return {
    archives,
    result: comparison.data,
    ensembleResult: profiles.data,
    queryError: profiles.error || comparison.error,
    markerSession,
    markerResult: marker.data,
    markerError: marker.error,
  };
}
