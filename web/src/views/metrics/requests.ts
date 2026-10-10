import { api, scope } from "../../api/client";
import type { ViewState } from "../../state/types";
import type { MetricGrid } from "./metricGrid";
import { readLibrary } from "./program";
import type {
  MetricAttribute,
  MetricPreset,
  MetricProgram,
  MetricResult,
  StudioData,
} from "./types";

export const errorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);
export function evaluateMetric(
  program: MetricProgram,
  grid: MetricGrid,
  snapshot: ViewState,
  signal?: AbortSignal,
  pixelDetails = false,
): Promise<MetricResult> {
  if (!grid.queryable)
    return Promise.resolve({ metric: { name: program.name, unit: program.unit }, series: [] });
  return api<MetricResult>(
    "metric/evaluate",
    {},
    {
      ...scope({}, snapshot),
      ...program,
      formulas: readLibrary(snapshot.metricLibrary),
      bins: grid.bins,
      ...(pixelDetails ? { pixelDetails: true } : {}),
    },
    signal,
  );
}
export async function loadStudio(
  program: MetricProgram,
  grid: MetricGrid,
  snapshot: ViewState,
  signal: AbortSignal,
): Promise<StudioData> {
  const selectedParadigm = Object.values(program.sources).find(
    (source) => source.type?.startsWith("io_") && source.paradigm,
  )?.paradigm;
  const [result, presets, attributes] = await Promise.allSettled([
    evaluateMetric(program, grid, snapshot, signal),
    api<MetricPreset[]>(
      "metric/presets",
      { id: snapshot.id, ...(selectedParadigm ? { paradigm: String(selectedParadigm) } : {}) },
      undefined,
      signal,
    ),
    api<MetricAttribute[]>("metric/attributes", { id: snapshot.id }, undefined, signal),
  ]);
  return {
    evaluation:
      result.status === "fulfilled"
        ? { status: "ready", result: result.value }
        : { status: "error", message: errorMessage(result.reason) },
    presets: presets.status === "fulfilled" ? presets.value : [],
    presetError: presets.status === "rejected" ? errorMessage(presets.reason) : "",
    attributes: attributes.status === "fulfilled" ? attributes.value : [],
    attributeError: attributes.status === "rejected" ? errorMessage(attributes.reason) : "",
  };
}
