import { getState } from "../state/store";
import { regions, color, shortLoc } from "../state/selectors";
import { esc } from "../lib/escape";
import { duration } from "../lib/format/time";
import { num } from "../lib/format/numbers";
import { inspectSpan } from "../state/inspection";
import { canvas, clipRect, strokeLine } from "./canvas";
import { axes, timeAt } from "./axes";
import { bindChart } from "./interactions";
import { drawLocationLabel } from "./locationLabel";
import type {
  ChartCanvas,
  ChartHit,
  ChartOptions,
  TimelineChartData,
  TimelineChartMessage,
  TimelineChartRow,
} from "./types";

export function drawTimeline(
  element: HTMLCanvasElement,
  data: TimelineChartData,
  visible: readonly string[],
  detail = false,
  messages: readonly TimelineChartMessage[] = [],
  options: ChartOptions<TimelineChartRow> = {},
): ChartCanvas {
  const rows = data.rows;
  const state = getState();
  const locationNames = new Map(visible.map((id) => [id, shortLoc(id)]));
  // Detailed responses carry depth; aggregate responses use their location row.
  const depth = detail
    ? Math.min(100, rows.reduce((m, r) => Math.max(m, r.depth!), 0) + 1)
    : visible.length;
  const rh = detail ? 25 : 35;
  const height = Math.max(160, Math.min(2700, depth * rh + 66));
  const g = canvas(element, height),
    { ctx, w, c } = g,
    left = Math.min(176, Math.max(120, w * 0.23)),
    x = axes(g, state.start, state.end, left, 32, 24),
    hits: ChartHit<TimelineChartRow>[] = [];
  ctx.font = "11px system-ui,sans-serif";
  for (let i = 0; i < depth; i++) {
    const y = 33 + i * rh;
    ctx.fillStyle = i % 2 ? c.grid + "60" : c.panel;
    ctx.fillRect(0, y, w, rh);
    ctx.fillStyle = c.muted;
    if (detail) ctx.fillText(`Depth ${i}`, 10, y + rh * 0.62);
    else drawLocationLabel(g, visible[i], 10, y, left - 20, rh);
    ctx.strokeStyle = c.grid;
    strokeLine(ctx, left, y + rh, w, y + rh);
  }
  clipRect(ctx, left, 31, w - left - 14, height - 56);
  for (const r of rows) {
    const row = detail ? r.depth! : visible.indexOf(r.location);
    if (row < 0 || row >= depth) continue;
    const a = Math.max(left, x(r.start)),
      b = Math.min(w - 15, x(r.end));
    if (b < a) continue;
    const y = 37 + row * rh;
    const fill = color(r.region, state.groupBy === "group");
    const name = regions[r.region]?.name || r.region;
    const locationName = locationNames.get(r.location) ?? shortLoc(r.location);
    ctx.globalAlpha = state.selectedRegion && state.selectedRegion !== String(r.region) ? 0.72 : 1;
    ctx.fillStyle = fill;
    ctx.fillRect(a, y, Math.max(0.65, b - a), rh - 8);
    ctx.globalAlpha = 1;
    if (b - a > 65) {
      clipRect(ctx, a + 2, y, b - a - 4, rh - 8);
      ctx.fillStyle = "#fff";
      ctx.font = "10px system-ui,sans-serif";
      ctx.fillText(name, a + 5, y + (rh - 8) / 2 + 3);
      ctx.restore();
    }
    if (r.incomplete) {
      ctx.strokeStyle = "#ba3948";
      ctx.strokeRect(a, y, b - a, rh - 8);
    }
    hits.push({
      x: a,
      y,
      w: Math.max(2, b - a),
      h: rh - 8,
      data: r,
      tip: () =>
        `<strong>${esc(name)}</strong>${esc(locationName)}<br>${duration(r.start)} → ${duration(r.end)}<br>${detail ? "Inclusive" : "Visible interval"}: ${duration(r.end - r.start)}${r.count != null && r.count > 1 ? `<br>${num(r.count, 0)} intervals coalesced at this resolution` : ""}`,
    });
  }
  if (!detail && state.showMessages) {
    ctx.strokeStyle = g.dark ? "#ecf2ff77" : "#263c6477";
    ctx.fillStyle = ctx.strokeStyle;
    ctx.lineWidth = 0.7;
    for (const m of messages) {
      const a = m.source == null ? -1 : visible.indexOf(m.source),
        b = m.target == null ? -1 : visible.indexOf(m.target);
      if (a < 0 || b < 0 || m.start == null || m.end == null) continue;
      const x1 = x(m.start),
        x2 = x(m.end),
        y1 = 33 + a * rh + rh / 2,
        y2 = 33 + b * rh + rh / 2;
      strokeLine(ctx, x1, y1, x2, y2);
      const ang = Math.atan2(y2 - y1, x2 - x1);
      ctx.beginPath();
      ctx.moveTo(x2, y2);
      ctx.lineTo(x2 - 5 * Math.cos(ang - 0.45), y2 - 5 * Math.sin(ang - 0.45));
      ctx.lineTo(x2 - 5 * Math.cos(ang + 0.45), y2 - 5 * Math.sin(ang + 0.45));
      ctx.fill();
    }
  }
  ctx.restore();
  bindChart(g, hits, timeAt(g, left), {
    onClick: (h) => inspectSpan(h.data.id),
    ...options,
  });
  return g;
}
