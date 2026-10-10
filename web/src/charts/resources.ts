import { getState } from "../state/store";
import { palette } from "../lib/color/palette";
import { hash } from "../lib/color/hash";
import { esc } from "../lib/escape";
import { locName } from "../state/selectors";
import { bytes } from "../lib/format/bytes";
import { duration } from "../lib/format/time";
import { inspectObject } from "../state/inspection";
import { canvas, clipRect } from "./canvas";
import { axes, timeAt } from "./axes";
import { bindChart } from "./interactions";
import type { ResourceChartData, ResourceChartRow, ChartHit, ChartOptions } from "./types";

export function drawResources(
  element: HTMLCanvasElement,
  data: ResourceChartData,
  options: ChartOptions<ResourceChartRow> = {},
): void {
  const rows = data.rows.filter(
      (r): r is ResourceChartRow & { readonly end: number } => r.end != null,
    ),
    keys = [...new Set(rows.map((r) => (getState().ioMode === "io" ? r.file : r.win)))].slice(
      0,
      30,
    );
  const g = canvas(element, Math.max(150, keys.length * 31 + 64)),
    { ctx, w, c } = g,
    left = 180,
    x = axes(g, getState().start, getState().end, left, 32, 20),
    hits: ChartHit<ResourceChartRow>[] = [];
  keys.forEach((key, i) => {
    ctx.fillStyle = c.muted;
    ctx.font = "10px system-ui,sans-serif";
    clipRect(ctx, 8, 31 + i * 31, left - 18, 30);
    ctx.fillText(
      getState().ioMode === "io"
        ? getState().meta!.files[String(key)] || `File ${key}`
        : `Window ${key}`,
      8,
      52 + i * 31,
    );
    ctx.restore();
  });
  for (const r of rows) {
    const i = keys.indexOf(getState().ioMode === "io" ? r.file : r.win);
    if (i < 0) continue;
    const a = Math.max(left, x(r.start)),
      b = Math.min(w - 15, x(r.end));
    ctx.fillStyle = palette[hash(r.operation) % palette.length]!;
    ctx.fillRect(a, 38 + i * 31, Math.max(1, b - a), 21);
    hits.push({
      x: a,
      y: 38 + i * 31,
      w: Math.max(3, b - a),
      h: 21,
      data: r,
      tip: `<strong>${esc(r.operation)}</strong>${esc(locName(r.location))}<br>${bytes(r.bytes)} · ${duration(r.end - r.start)}`,
    });
  }
  bindChart(g, hits, timeAt(g, left), {
    menu: false,
    onClick: (h) => inspectObject(h.data.operation, h.data),
    ...options,
  });
}
