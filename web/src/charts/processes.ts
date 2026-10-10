import { setView } from "../state/viewActions";
import { groupColor, locName } from "../state/selectors";
import { esc } from "../lib/escape";
import { duration } from "../lib/format/time";
import { updateState } from "../state/store";
import { canvas } from "./canvas";
import { bindChart } from "./interactions";
import { drawLocationLabel } from "./locationLabel";
import type { ProcessChartRow, ChartHit, ChartOptions } from "./types";

export function drawProcesses(
  element: HTMLCanvasElement,
  rows: readonly ProcessChartRow[],
  options: ChartOptions<ProcessChartRow> = {},
): void {
  const g = canvas(element, Math.max(180, Math.min(1100, rows.length * 29 + 45))),
    { ctx, w, c } = g,
    left = Math.min(200, Math.max(120, w * 0.3)),
    max = Math.max(1e-30, ...rows.map((r) => r.exclusive)),
    hits: ChartHit<ProcessChartRow>[] = [];
  rows.slice(0, 36).forEach((r, i) => {
    const y = 16 + i * 29;
    ctx.fillStyle = c.muted;
    ctx.font = "11px system-ui,sans-serif";
    drawLocationLabel(g, r.id, 10, y - 3, left - 20, 29);
    let at = left;
    for (const [group, seconds] of Object.entries(r.groups)) {
      const bw = (seconds / max) * (w - left - 95);
      ctx.fillStyle = groupColor(group);
      ctx.fillRect(at, y, bw, 20);
      hits.push({
        x: at,
        y,
        w: bw,
        h: 20,
        data: r,
        tip: `<strong>${esc(locName(r.id))}</strong>${esc(group)} · ${duration(seconds)}`,
      });
      at += bw;
    }
    ctx.fillStyle = c.muted;
    ctx.font = "10px ui-monospace,monospace";
    ctx.fillText(duration(r.exclusive), at + 8, y + 14);
  });
  bindChart(g, hits, () => 0, {
    range: false,
    menu: false,
    onClick: (h) => {
      updateState({ detailLocation: h.data.id });
      setView("timeline");
    },
    ...options,
  });
}
