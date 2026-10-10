import { color } from "../state/selectors";
import { esc } from "../lib/escape";
import { duration } from "../lib/format/time";
import { num } from "../lib/format/numbers";
import { inspectObject } from "../state/inspection";
import { canvas, clipRect } from "./canvas";
import { bindChart } from "./interactions";
import type { FlameChartRow, ChartHit, ChartOptions } from "./types";

export function drawFlame(
  element: HTMLCanvasElement,
  rows: readonly FlameChartRow[],
  options: ChartOptions<FlameChartRow> = {},
): void {
  const depth = rows.reduce((m, r) => Math.max(m, r.depth), 0);
  const g = canvas(element, Math.max(200, Math.min(1200, (depth + 1) * 29 + 35))),
    { ctx, w } = g;
  const children: Record<number, FlameChartRow[]> = {};
  rows.forEach((r) => (children[r.parent] ??= []).push(r));
  const roots = children[0] || [];
  const weights = new Map<number, number>();
  function weight(r: FlameChartRow): number {
    const cached = weights.get(r.id);
    if (cached !== undefined) return cached;
    const value = Math.max(
      r.inclusive,
      (children[r.id] || []).reduce((sum, c) => sum + weight(c), 0),
    );
    weights.set(r.id, value);
    return value;
  }
  const total = roots.reduce((s, r) => s + weight(r), 0);
  const hits: ChartHit<FlameChartRow>[] = [];
  function draw(
    list: FlameChartRow[],
    x: number,
    y: number,
    width: number,
    parentTotal: number,
  ): void {
    let at = x;
    for (const r of list.toSorted((a, b) => b.inclusive - a.inclusive)) {
      const bw = (weight(r) / Math.max(parentTotal, 1e-30)) * width;
      if (bw < 0.5) continue;
      ctx.fillStyle = color(r.region);
      ctx.fillRect(at + 1, y, bw - 1, 24);
      ctx.fillStyle = "#fff";
      ctx.font = "10px system-ui,sans-serif";
      if (bw > 40) {
        clipRect(ctx, at + 3, y, bw - 5, 24);
        ctx.fillText(r.name, at + 5, y + 16);
        ctx.restore();
      }
      hits.push({
        x: at,
        y,
        w: bw,
        h: 24,
        data: r,
        tip: `<strong>${esc(r.name)}</strong>Inclusive ${duration(r.inclusive)}<br>Exclusive ${duration(r.exclusive)} · ${num(r.calls, 0)} calls`,
      });
      draw(children[r.id] || [], at, y + 29, bw, weight(r));
      at += bw;
    }
  }
  draw(roots, 5, 10, w - 10, total);
  bindChart(g, hits, () => 0, {
    range: false,
    menu: false,
    onClick: (h) => inspectObject(h.data.name, h.data),
    ...options,
  });
}
