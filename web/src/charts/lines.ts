import { getState } from "../state/store";
import { palette } from "../lib/color/palette";
import { compact, num } from "../lib/format/numbers";
import { esc } from "../lib/escape";
import { locName } from "../state/selectors";
import { duration } from "../lib/format/time";
import { inspectObject } from "../state/inspection";
import { canvas, strokeLine } from "./canvas";
import { axes, timeAt } from "./axes";
import { bindChart } from "./interactions";
import type { LineChartData, LineChartSample, ChartHit, ChartOptions } from "./types";

export function drawLines(
  element: HTMLCanvasElement,
  result: LineChartData,
  height = 350,
  options: ChartOptions<LineChartSample> = {},
): void {
  const series = result.series;
  const g = canvas(element, height),
    { ctx, w, h, c } = g,
    left = 85,
    x = axes(g, getState().start, getState().end, left, 36, 36);
  if (!series.some((s) => s.points.length)) {
    ctx.fillStyle = c.muted;
    ctx.fillText("No metric samples in the selected interval / locations.", 20, 60);
    return;
  }
  let min = Infinity,
    max = -Infinity;
  // Evaluated curves may have interior extrema absent from raw observations.
  for (const s of series)
    for (const [, value] of s.points)
      if (value != null && Number.isFinite(value)) {
        min = Math.min(min, value);
        max = Math.max(max, value);
      }
  if (!Number.isFinite(min + max)) return;
  if (min === max) {
    min -= Math.abs(min) * 0.05 || 1;
    max += Math.abs(max) * 0.05 || 1;
  }
  const y = (v: number): number => h - 42 - ((v - min) / (max - min)) * (h - 90),
    hits: ChartHit<LineChartSample>[] = [];
  ctx.fillStyle = c.muted;
  ctx.font = "10px ui-monospace,monospace";
  for (let i = 0; i <= 4; i++) {
    const val = min + ((max - min) * i) / 4,
      py = y(val);
    ctx.strokeStyle = c.grid;
    strokeLine(ctx, left, py, w - 15, py);
    ctx.textAlign = "right";
    ctx.fillText(compact(val), left - 10, py + 4);
  }
  ctx.textAlign = "left";
  ctx.fillText(result.unit || result.metric?.unit || "", 10, 18);
  const metricName = esc(result.metric?.name);
  const unit = esc(result.unit || result.metric?.unit || "");
  series.forEach((s, index) => {
    const seriesName = esc(s.name || locName(s.location));
    ctx.strokeStyle = palette[index % palette.length]!;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    let pen = false,
      previousValue: number | null = null;
    const stepped = s.interpolation === "previous" || s.interpolation === "constant";
    s.points.forEach(([t, v]) => {
      if (v == null || !Number.isFinite(v)) {
        if (pen && stepped) ctx.lineTo(x(t), y(previousValue!));
        pen = false;
        return;
      }
      if (!pen) ctx.moveTo(x(t), y(v));
      else {
        if (stepped) ctx.lineTo(x(t), y(previousValue!));
        ctx.lineTo(x(t), y(v));
      }
      pen = true;
      previousValue = v;
      hits.push({
        x: x(t) - 4,
        y: y(v) - 6,
        w: 8,
        h: 12,
        data: { start: t, end: t, location: s.location },
        tip: () =>
          `<strong>${metricName}</strong>${seriesName}<br>${duration(t)} · ${num(v, 6)} ${unit}`,
      });
    });
    ctx.stroke();
  });
  bindChart(g, hits, timeAt(g, left), {
    menu: false,
    onClick: (h) => inspectObject("Metric sample", h.data),
    ...options,
  });
}
