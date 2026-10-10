import { api } from "../../api/client";
import type { TraceMeta, TraceListing, OverviewData } from "../../api/types/common";
import type { SavedSession } from "../types";
import { getState, getUi, updateState, updateUi } from "../store";
import { setRange } from "../rangeActions";
import { setView } from "../viewActions";
import { restoreState } from "../session";
import { readTracePreferences } from "../persistence";
import { beginTraceLoad, isCurrentTraceLoad } from "./requests";

export async function loadTrace(
  id: string,
  restore?: SavedSession | null,
  request = beginTraceLoad(),
): Promise<void> {
  const meta = await api<TraceMeta>("meta", { id });
  if (!isCurrentTraceLoad(request)) return;
  const { bookmarks, colors } = readTracePreferences(meta.path);
  updateState({
    id,
    meta,
    locations: new Set(meta.locations.map((location) => location.id)),
    region: "",
    exclude: "",
    group: "",
    detailLocation: null,
    metric: meta.metrics[0]?.id || "",
    metricY: meta.metrics[1]?.id || meta.metrics[0]?.id || "",
    history: [],
    historyIndex: -1,
    timelinePage: 0,
    eventOffset: 0,
    eventKind: "",
    eventSearch: "",
    messageOffset: 0,
    messageFilter: {},
    definitionOffset: 0,
    definitionKind: "",
    definitionSearch: "",
    radarGroup: null,
    radarPage: 0,
    selectedRegion: null,
    counterDerived: false,
    analysisPage: 0,
    relationshipOffset: 0,
    relationshipKind: {},
    relationshipSearch: "",
    waitOffset: 0,
    waitCauseOffset: 0,
    waitRequestOffset: 0,
    waitCollectiveOffset: 0,
    waitProbeOffset: 0,
    waitRmaLockOffset: 0,
    gpuExternalOffset: 0,
    waitCategory: "",
    alignment: null,
    ensemble: null,
    ensembleApplied: false,
    markerInputs: {},
    markerSession: null,
    markerWindow: null,
    markerSelectedLocationOnly: false,
    comparisonRuns: [],
    runAlignmentConstraints: {},
    alignmentApplied: false,
    metricProgram: null,
    metricOverlay: false,
    bookmarks,
    colors,
  });
  updateUi({ overviewData: null });
  setRange(0, meta.duration);
  localStorage.setItem("lastTrace", id);
  setView(restore?.view || location.hash.slice(1) || "timeline");
  if (restore) restoreState(restore);
  if (!getUi().embedded) {
    const overviewData = await api<OverviewData>("overview", {
      id,
      start: 0,
      end: meta.duration,
      bins: 300,
    });
    if (isCurrentTraceLoad(request) && getState().id === id) updateUi({ overviewData });
  }
  const traces = await api<TraceListing[]>("traces");
  if (isCurrentTraceLoad(request)) updateUi({ traces });
}
