import { canvas } from "../../charts/canvas";
import { bindChart } from "../../charts/interactions";
import type { ChartHit } from "../../charts/types";
import { esc } from "../../lib/escape";
import { num } from "../../lib/format/numbers";
import { duration } from "../../lib/format/time";
import { inspectObject } from "../../state/inspection";
import type { NamedIdleRow } from "./types";

export function drawIdle(
  element: HTMLCanvasElement,
  rows: readonly NamedIdleRow[],
  failed: boolean,
) {
  const visible = rows.slice(0, 64);
  const height = Math.max(100, 40 + visible.length * 30);
  const g = canvas(element, height);
  const { ctx, w, c } = g;
  const left = Math.min(290, w * 0.42);
  const width = Math.max(20, w - left - 72);
  const hits: ChartHit<NamedIdleRow>[] = [];
  if (!visible.length) {
    ctx.fillStyle = c.muted;
    ctx.fillText(
      failed
        ? "Idle statistics unavailable."
        : "No accelerator streams with supported topology in this selection.",
      12,
      45,
    );
  }
  visible.forEach((row, index) => {
    const y = 12 + index * 30;
    ctx.save();
    ctx.beginPath();
    ctx.rect(8, y, left - 16, 28);
    ctx.clip();
    ctx.fillStyle = c.text;
    ctx.font = "11px system-ui,sans-serif";
    ctx.fillText(row.name, 8, y + 17);
    ctx.restore();
    ctx.fillStyle = c.grid;
    ctx.fillRect(left, y + 4, width, 18);
    ctx.fillStyle = c.accent;
    ctx.fillRect(left, y + 4, (width * (row.idlePercentage ?? 0)) / 100, 18);
    ctx.fillStyle = c.text;
    ctx.font = "10px ui-monospace,monospace";
    ctx.fillText(
      row.idlePercentage == null ? "—" : num(row.idlePercentage, 2) + "%",
      left + width + 7,
      y + 17,
    );
    hits.push({
      x: 0,
      y,
      w,
      h: 28,
      data: row,
      tip: `<strong>${esc(row.name)}</strong>Idle ${duration(row.idle)}<br>Function activity ${duration(row.active)}<br>Window ${duration(row.duration)}`,
    });
  });
  if (rows.length > visible.length) {
    ctx.fillStyle = c.muted;
    ctx.fillText(
      `First ${visible.length} of ${rows.length} rows; the table and export contain every row.`,
      8,
      height - 8,
    );
  }
  return bindChart(g, hits, () => 0, {
    range: false,
    menu: false,
    onClick: (hit) => inspectObject("GPU idle statistics · " + hit.data.name, hit.data),
  });
}
