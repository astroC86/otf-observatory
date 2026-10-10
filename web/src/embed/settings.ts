import type { AppState } from "../state/types";
import { views } from "../state/viewActions";
import { getState } from "../state/store";
const text = (value: unknown) => value === null || typeof value === "string";
const object = (value: unknown) =>
  value === null || (typeof value === "object" && !Array.isArray(value));
const flag = (value: unknown) => typeof value === "boolean";
const offset = (value: unknown): value is number =>
  typeof value === "number" && Number.isInteger(value) && value >= 0;
const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

// Consecutive fields share a validator; this order is the wire/saved-layout order.
const schema: [string, (value: unknown) => boolean][] = [
  [
    "view",
    (value) =>
      typeof value === "string" && value !== "workspace" && views.some(([id]) => id === value),
  ],
  ["detailLocation metric metricY counterMode", text],
  ["counterDerived", flag],
  ["expression groupBy", text],
  ["showMessages", flag],
  ["ioMode callMode processMetric matrixMetric", text],
  ["metricProgram", object],
  ["metricOverlay", flag],
  ["metricStepSize", (value) => offset(value) && value > 0 && value <= 0xffffffff],
  ["metricLibrary", object],
  ["comparison", text],
  ["shift", finite],
  ["alignmentMode", text],
  ["alignmentScale", (value) => finite(value) && value > 0],
  ["alignment", object],
  ["alignmentApplied", flag],
  ["runAlignmentConstraints", object],
  [
    "comparisonRuns",
    (value) =>
      Array.isArray(value) &&
      value.length <= 15 &&
      value.every((id: unknown) => typeof id === "string"),
  ],
  ["ensemble", object],
  ["ensembleMode", text],
  ["ensembleApplied", flag],
  ["markerInputs markerSession markerWindow", object],
  ["markerSelectedLocationOnly", flag],
  ["waitSource waitCategory", text],
  ["relationshipKind", object],
  ["relationshipSearch radarGroup", text],
  ["radarPage timelinePage", offset],
  ["messageBy transferSummaryGroup transferSummaryMetric transferSummaryTypes", text],
  ["transferMatrixMetric", text],
  ["transferMatrixMaxGroups", offset],
  ["transferMatrixTypes transferTimelineGroup transferTimelineMetric", text],
  ["transferTimelineBins transferTimelineMaxKeys", offset],
  ["transferTimelineTypes", text],
  ["messageFilter", object],
  ["messageOffset", offset],
  ["eventKind eventSearch", text],
  ["eventOffset", offset],
  ["definitionKind definitionSearch", text],
  ["definitionOffset", offset],
  ["traceMode alignmentAnchor", text],
  ["relationshipEdges", flag],
  ["gpuIdleLevel", (value) => value === "devices" || value === "contexts" || value === "locations"],
  ["gpuIdleEventMode", (value) => value === 0 || value === 1 || value === 2],
  ["relationshipOffset analysisPage waitOffset waitCauseOffset", offset],
  ["waitRequestOffset waitCollectiveOffset waitProbeOffset", offset],
  ["waitRmaLockOffset gpuExternalOffset", offset],
];
const fields = schema.flatMap(([names, accepts]) =>
  names.split(" ").map((name) => [name, accepts] as const),
);
export type PanelSettings = Record<string, unknown>;

export function panelSettings(source: object = getState(), validate = false): PanelSettings {
  const values = source as PanelSettings;
  const settings: PanelSettings = {};
  for (const [key, accepts] of fields) {
    const value = values[key];
    if (validate ? Object.hasOwn(values, key) && accepts(value) : value !== undefined)
      settings[key] = value;
  }
  return settings;
}

export function restoreSettings(defaults: PanelSettings, incoming: object): Partial<AppState> {
  // Nullable strings/objects remain shallow protocol values, not deep AppState validation.
  return panelSettings(
    { ...(JSON.parse(JSON.stringify(defaults)) as PanelSettings), ...incoming },
    true,
  ) as Partial<AppState>;
}
