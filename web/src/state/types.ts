import type { ReactNode } from "react";
import type {
  TraceMeta,
  JsonObject,
  Bookmark,
  MessageFilter,
  SpanResponse,
  TraceListing,
  OverviewData,
} from "../api/types/common";
import type {
  Alignment,
  Ensemble,
  MarkerInput,
  MarkerSession,
  TimeRange,
} from "../views/compare/types";
import type { DockLayout } from "../workspace/types";

// Field order is the saved-session order. Optional fields are inserted only by
// their actions or restoration, never by the initial state.
const defaults = {
  id: null as string | null,
  meta: null as TraceMeta | null,
  view: "timeline",
  start: 0,
  end: 0,
  locations: new Set<string>() as ReadonlySet<string>,
  region: "",
  exclude: "",
  group: "",
  history: [] as readonly [number, number][],
  historyIndex: -1,
  selectedRegion: null as string | null,
  detailLocation: null as string | null,
  showMessages: false,
  timelinePage: 0,
  groupBy: "function",
  metric: "",
  metricY: "",
  counterMode: "value",
  expression: "x",
  counterDerived: false,
  matrixMetric: "bytes",
  messageBy: "size",
  transferSummaryGroup: "size",
  transferSummaryMetric: "count",
  transferSummaryTypes: "",
  transferMatrixMetric: "bytes.sum",
  transferMatrixMaxGroups: 32,
  transferMatrixTypes: "",
  transferTimelineGroup: "type",
  transferTimelineMetric: "count",
  transferTimelineBins: 100,
  transferTimelineMaxKeys: 20,
  transferTimelineTypes: "",
  messageOffset: 0,
  eventOffset: 0,
  eventKind: "",
  eventSearch: "",
  definitionKind: "",
  definitionSearch: "",
  traceMode: "properties",
  ioMode: "io",
  callMode: "tree",
  bookmarks: [] as readonly Bookmark[],
  comparison: null as string | null,
  shift: 0,
  collapsed: new Set<number>() as ReadonlySet<number>,
  colors: {} as Readonly<Record<string, string>>,
  tableSearch: "",
  processMetric: "exclusive",
  messageFilter: {} as Readonly<MessageFilter>,
  definitionOffset: 0,
  metricProgram: null as JsonObject | null,
  metricOverlay: false,
  metricStepSize: 4,
  alignment: null as Alignment | null,
  alignmentApplied: false,
  alignmentAnchor: "",
  alignmentScale: 1,
  alignmentMode: "affine",
  alignmentConstraints: "",
  runAlignmentConstraints: {} as Readonly<Record<string, string>>,
  comparisonRuns: [] as readonly string[],
  ensemble: null as Ensemble | null,
  ensembleMode: "piecewise",
  ensembleApplied: false,
  markerInputs: {} as Readonly<Record<string, MarkerInput>>,
  markerSession: null as MarkerSession | null,
  markerWindow: null as TimeRange | null,
  markerSelectedLocationOnly: false,
  waitSource: "waits",
  waitCategory: "",
  waitOffset: 0,
  waitCauseOffset: 0,
  waitRequestOffset: 0,
  waitCollectiveOffset: 0,
  waitProbeOffset: 0,
  waitRmaLockOffset: 0,
  gpuExternalOffset: 0,
  relationshipKind: {} as Readonly<Record<string, string>>,
  relationshipSearch: "",
  relationshipEdges: true,
  gpuIdleLevel: "devices",
  gpuIdleEventMode: 0,
  relationshipOffset: 0,
  analysisPage: 0,
  radarGroup: null as string | null,
  radarPage: 0,
};
export type AppState = typeof defaults & {
  metricLibrary?: JsonObject;
  dockLayout?: DockLayout;
};
export const initialState: Readonly<AppState> = Object.freeze(defaults);
export type ViewState = Readonly<Omit<AppState, "meta"> & { meta: TraceMeta; epoch: number }>;
export type SavedSession = Partial<
  Omit<AppState, "meta" | "locations" | "history" | "historyIndex" | "collapsed">
> & {
  format: "otf-observatory-session";
  version: 1;
  path?: string;
  locations: string[];
};
export type StatePatch = Partial<AppState> | ((previous: Readonly<AppState>) => Partial<AppState>);
export interface InspectorContent {
  before?: ReactNode;
  after?: ReactNode;
}
export type ContextValue =
  | { kind: "span"; span: SpanResponse }
  | ({ kind: "object"; title: string; object: unknown } & InspectorContent)
  | { kind: "content"; title: string; content: ReactNode };
const uiDefaults = {
  initialized: false,
  epoch: 0,
  busy: false,
  status: "Ready",
  statusIcon: true,
  queryTime: "",
  selection: "Select a trace to begin",
  explorerSearch: "",
  showMetrics: false,
  sidebarCollapsed: false,
  toast: null as string | null,
  context: null as ContextValue | null,
  contextVisible: false,
  menu: null as { left: number; top: number; row?: object; export?: boolean } | null,
  dialog: null as "open" | "loading" | "help" | null,
  openError: null as string | null,
  loadingTitle: "Opening trace",
  loadingPhase: "Reading archive definitions…",
  loadingCount: "",
  rangeStart: "0",
  rangeEnd: "0",
  theme: (localStorage.getItem("theme") === "dark" ? "dark" : "light") as "light" | "dark",
  embedded: new URLSearchParams(location.search).get("embed") === "1",
  tooltip: null as { content: ReactNode; x: number; y: number } | null,
  brush: null as { left: number; top: number; width: number; height: number } | null,
  traces: [] as readonly TraceListing[],
  overviewData: null as OverviewData | null,
};
export type UiState = typeof uiDefaults;
export const initialUi: Readonly<UiState> = Object.freeze(uiDefaults);
