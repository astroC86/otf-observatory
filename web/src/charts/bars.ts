import { getState } from "../state/store";
import { color } from "../state/selectors";
import { num } from "../lib/format/numbers";
import { bytes } from "../lib/format/bytes";
import { duration } from "../lib/format/time";
import { esc } from "../lib/escape";
import { inspectObject } from "../state/inspection";
import { canvas, clipRect } from "./canvas";
import { bindChart } from "./interactions";
import type { BarChartMetric, BarChartRow, ChartHit, ChartOptions } from "./types";

export function drawBars(
  element: HTMLCanvasElement,
  rows: readonly BarChartRow[],
  key: BarChartMetric = "exclusive",
  height = 260,
  options: ChartOptions<BarChartRow> = {},
): void {
  const g = canvas(element, height),
    { ctx, w, c } = g;
  const data = rows.slice(0, 10),
    max = Math.max(1e-30, ...data.map((r) => r[key] || 0)),
    left = Math.min(210, w * 0.44),
    rh = (height - 28) / Math.max(1, data.length),
    hits: ChartHit<BarChartRow>[] = [];
  data.forEach((r, i) => {
    const y = 13 + i * rh;
    ctx.fillStyle = c.text;
    ctx.font = "11px system-ui,sans-serif";
    clipRect(ctx, 12, y, left - 23, rh);
    ctx.fillText(String(r.name || r.label || r.id), 12, y + rh * 0.6);
    ctx.restore();
    ctx.fillStyle = color(r.region || r.id, getState().groupBy === "group");
    const width = ((r[key] || 0) / max) * (w - left - 95);
    ctx.fillRect(left, y + rh * 0.2, width, Math.max(5, rh * 0.5));
    ctx.fillStyle = c.muted;
    ctx.font = "10px ui-monospace,monospace";
    const value =
      key === "count" ? num(r[key], 0) : key === "bytes" ? bytes(r[key]) : duration(r[key]);
    ctx.fillText(value, left + width + 7, y + rh * 0.6);
    hits.push({
      x: 0,
      y,
      w,
      h: rh,
      data: r,
      tip: `<strong>${esc(r.name || r.label)}</strong>${key}: ${value}`,
    });
  });
  bindChart(g, hits, () => 0, {
    range: false,
    menu: false,
    onClick: (h) => inspectObject(h.data.name || h.data.label, h.data),
    ...options,
  });
}
