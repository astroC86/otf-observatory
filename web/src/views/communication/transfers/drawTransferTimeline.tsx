import { canvas } from "../../../charts/canvas";
import { bindChart } from "../../../charts/interactions";
import type { ChartHit } from "../../../charts/types";
import { palette } from "../../../lib/color/palette";
import { bytes } from "../../../lib/format/bytes";
import { num } from "../../../lib/format/numbers";
import { duration } from "../../../lib/format/time";
import type { TransferTimelineModel, TransferTimelineRow } from "./timelineModel";

export interface TransferTimelineChartSpec {
  readonly model: TransferTimelineModel;
  readonly error: string | null;
  readonly inspectBin: (row: TransferTimelineRow) => void;
}

export function drawTransferTimeline(
  element: HTMLCanvasElement,
  spec: TransferTimelineChartSpec,
): () => void {
  const { model, error, inspectBin } = spec;
  const { series, bounds, colors, rows, maximum, format, hasTransfers } = model;
  const g = canvas(element, 285);
  const { ctx, w, c } = g;
  const left = Math.min(92, Math.max(40, w * 0.16));
  const right = 12;
  const top = 28;
  const bottom = 245;
  const width = Math.max(1, w - left - right);
  const binWidth = width / Math.max(1, series.length);
  const hits: ChartHit<TransferTimelineRow>[] = [];
  ctx.fillStyle = c.muted;
  ctx.font = "10px system-ui,sans-serif";

  if (!rows.length || !hasTransfers) {
    ctx.fillText(
      error ? "Transfer timeline unavailable." : "No supported transfers start in these bins.",
      12,
      46,
    );
  }
  for (let index = 0; index <= 4; index++) {
    const y = bottom - ((bottom - top) * index) / 4;
    ctx.strokeStyle = c.grid;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(w - right, y);
    ctx.stroke();
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, y - 9, left - 6, 18);
    ctx.clip();
    ctx.fillText(format((maximum * index) / 4), 3, y + 3);
    ctx.restore();
  }
  series.forEach((bin, index) => {
    const x = left + index * binWidth;
    let y = bottom;
    for (const row of bin) {
      const height =
        ((Number.isFinite(row.value) ? Math.max(0, row.value) : 0) / maximum) * (bottom - top);
      ctx.fillStyle = colors.get(String(row.key)) || palette[0]!;
      ctx.fillRect(x, y - height, Math.max(0.25, binWidth - 0.6), height);
      y -= height;
    }
    hits.push({
      x,
      y: top,
      w: binWidth,
      h: bottom - top,
      data: rows[index]!,
      tip: (
        <>
          <strong>{`Bin ${index + 1}`}</strong>
          {`${duration(bounds[index])} – ${duration(bounds[index + 1])}`}
          <br />
          {`${num(rows[index]!.count, 0)} transfers · ${bytes(rows[index]!.bytes)}`}
          <br />
          Click to inspect group statistics
        </>
      ),
    });
  });
  if (bounds.length) {
    const start = bounds[0]!;
    const span = bounds.at(-1)! - start;
    const lastLabel = duration(start + (span * 4) / 4);
    const lastWidth = ctx.measureText(lastLabel).width;
    const lastLeft = left + width - lastWidth;
    let labelRight = -Infinity;
    for (let index = 0; index <= 4; index++) {
      const x = left + (width * index) / 4;
      const label = index === 4 ? lastLabel : duration(start + (span * index) / 4);
      const labelWidth = index === 4 ? lastWidth : ctx.measureText(label).width;
      const labelLeft = index === 4 ? x - labelWidth : index === 0 ? x : x - labelWidth / 2;
      ctx.fillStyle = c.muted;
      ctx.textAlign = index === 4 ? "right" : index === 0 ? "left" : "center";
      if (labelLeft >= labelRight + 1 && (index === 4 || labelLeft + labelWidth <= lastLeft - 1)) {
        ctx.fillText(label, x, 268);
        labelRight = labelLeft + labelWidth;
      }
    }
  }
  ctx.textAlign = "left";
  return bindChart(
    g,
    hits,
    (x) => bounds[0]! + ((x - left) / width) * (bounds.at(-1)! - bounds[0]!),
    {
      range: false,
      menu: false,
      onClick: (hit) => inspectBin(hit.data),
    },
  );
}
