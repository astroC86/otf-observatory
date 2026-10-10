import { canvas } from "../../../charts/canvas";
import { bindChart } from "../../../charts/interactions";
import type { ChartHit } from "../../../charts/types";
import { bytes } from "../../../lib/format/bytes";
import { num } from "../../../lib/format/numbers";
import { duration } from "../../../lib/format/time";
import { inspectObject } from "../../../state/inspection";
import type { TransferSummaryChartSpec, TransferSummaryRow } from "./summaryModel";

export function drawTransferSummary(
  element: HTMLCanvasElement,
  spec: TransferSummaryChartSpec,
): () => void {
  const { rows, visible, metric, format, maximum, height, error } = spec;
  const g = canvas(element, height);
  const { ctx, w, c } = g;
  const left = Math.min(270, w * 0.4);
  const width = Math.max(20, w - left - 100);
  const hits: ChartHit<TransferSummaryRow>[] = [];

  if (!visible.length) {
    ctx.fillStyle = c.muted;
    ctx.fillText(
      error ? "Transfer summary unavailable." : "No supported transfers start in this selection.",
      12,
      42,
    );
  }
  visible.forEach((row, index) => {
    const y = 12 + index * 29;
    const value = row[metric];
    ctx.save();
    ctx.beginPath();
    ctx.rect(8, y, left - 16, 25);
    ctx.clip();
    ctx.fillStyle = c.text;
    ctx.font = "11px system-ui,sans-serif";
    ctx.fillText(row.label, 8, y + 17);
    ctx.restore();
    ctx.fillStyle = c.accent;
    ctx.fillRect(left, y + 3, width * (Number.isFinite(value) ? value / maximum : 0), 18);
    ctx.fillStyle = c.text;
    ctx.fillText(format(value), left + width + 7, y + 17);
    hits.push({
      x: 0,
      y,
      w,
      h: 27,
      data: row,
      tip: (
        <>
          <strong>{row.label}</strong>
          {`${num(row.count, 0)} transfers`}
          <br />
          {`${bytes(row.byteSum)} · ${duration(row.durationSum)}`}
        </>
      ),
    });
  });
  if (rows.length > visible.length) {
    ctx.fillStyle = c.muted;
    ctx.fillText(
      `Largest ${visible.length} of ${rows.length} groups; all groups are in the table and export.`,
      8,
      height - 8,
    );
  }
  return bindChart(g, hits, () => 0, {
    range: false,
    menu: false,
    onClick: (hit) => inspectObject(`Transfer summary · ${hit.data.label}`, hit.data),
  });
}
