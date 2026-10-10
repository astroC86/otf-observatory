export const MAX_METRIC_CELLS = 2000;
export interface MetricGrid {
  width: number;
  step: number;
  requested: number;
  bins: number;
  capped: boolean;
  queryable: boolean;
}
export type MetricChartMode = "line" | "radar";
export function metricStep(value: unknown): number {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 && number <= 0xffffffff ? number : 4;
}
export function metricGrid(plotWidth: number, stepSize = 4): MetricGrid {
  const width = Math.max(0, Math.floor(Number(plotWidth) || 0));
  const step = metricStep(stepSize);
  const requested = Math.ceil(width / step);
  return {
    width,
    step,
    requested,
    bins: Math.min(MAX_METRIC_CELLS, requested),
    capped: requested > MAX_METRIC_CELLS,
    queryable: width > step,
  };
}
export function measureMetricGrid(
  element: HTMLCanvasElement,
  stepSize: number,
  mode: MetricChartMode = "line",
): MetricGrid {
  // Logical pixels, independent of device-pixel canvas backing dimensions.
  const width = Math.max(300, Math.floor(element.getBoundingClientRect().width));
  const left = mode === "radar" ? Math.min(205, width * 0.25) : 85;
  return metricGrid(width - left - 15, stepSize);
}
export function gridDescription(grid: MetricGrid): string {
  if (!grid.queryable) return "Widen the chart or decrease the pixel step to evaluate this metric.";
  return `${grid.step} px per cell · ${grid.bins} cells${grid.capped ? ` · Browser limit: ${MAX_METRIC_CELLS} of ${grid.requested} requested cells` : ""}`;
}
