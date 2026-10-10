import type { TransferLocationGroup } from "../../../api/types/transfers";
import { canvas } from "../../../charts/canvas";
import { bindChart } from "../../../charts/interactions";
import type { ChartHit } from "../../../charts/types";
import { num } from "../../../lib/format/numbers";
import { inspectObject } from "../../../state/inspection";
import {
  locationGroupLabel,
  type TransferMatrixModel,
  type TransferMatrixRow,
} from "./matrixModel";

type MatrixHit =
  | TransferMatrixRow
  | {
      readonly axis: "Sender" | "Receiver";
      readonly group: TransferLocationGroup;
    };

export interface TransferMatrixChartSpec {
  readonly model: TransferMatrixModel;
  readonly error: string | null;
  readonly inspectCell: (row: TransferMatrixRow) => void;
}

export function drawTransferMatrix(
  element: HTMLCanvasElement,
  spec: TransferMatrixChartSpec,
): () => void {
  const { model, error, inspectCell } = spec;
  const {
    height,
    senders,
    receivers,
    rows,
    maximum,
    metric,
    format,
    senderIndexes,
    receiverIndexes,
  } = model;
  const g = canvas(element, height);
  const { ctx, w, c } = g;
  const left = Math.min(170, w * 0.29);
  const top = 54;
  const width = Math.max(20, w - left - 24);
  const cellW = width / Math.max(1, receivers.length);
  const cellH = 20;
  const hits: ChartHit<MatrixHit>[] = [];
  ctx.font = "11px system-ui,sans-serif";

  if (!rows.length) {
    ctx.fillStyle = c.muted;
    ctx.fillText(
      error ? "Transfer matrix unavailable." : "No supported transfers start in this selection.",
      12,
      42,
    );
    return bindChart(g, hits, () => 0, { range: false, menu: false });
  }
  ctx.fillStyle = c.muted;
  ctx.fillText("Sender ↓", 8, 18);
  ctx.fillText("Receiver →", left, 18);
  receivers.forEach((group, index) => {
    const x = left + index * cellW;
    ctx.fillStyle = c.text;
    ctx.textAlign = "center";
    ctx.fillText(String(index + 1), x + cellW / 2, top - 10);
    hits.push({
      x,
      y: top - 25,
      w: cellW,
      h: 24,
      data: { axis: "Receiver", group },
      tip: (
        <>
          <strong>{`Receiver ${index + 1}`}</strong>
          {locationGroupLabel(group)}
        </>
      ),
    });
  });
  ctx.textAlign = "left";
  senders.forEach((group, index) => {
    const y = top + index * cellH;
    ctx.fillStyle = c.grid;
    ctx.fillRect(left, y, width, cellH - 1);
    ctx.save();
    ctx.beginPath();
    ctx.rect(6, y, left - 12, cellH);
    ctx.clip();
    ctx.fillStyle = c.text;
    ctx.fillText(`${index + 1}. ${locationGroupLabel(group)}`, 8, y + 14);
    ctx.restore();
    hits.push({
      x: 0,
      y,
      w: left - 3,
      h: cellH,
      data: { axis: "Sender", group },
      tip: (
        <>
          <strong>{`Sender ${index + 1}`}</strong>
          {locationGroupLabel(group)}
        </>
      ),
    });
  });
  rows.forEach((row) => {
    const x = left + receiverIndexes.get(row.target)! * cellW;
    const y = top + senderIndexes.get(row.source)! * cellH;
    ctx.globalAlpha =
      0.15 + 0.85 * Math.max(0, Math.min(1, Number.isFinite(row.value) ? row.value / maximum : 0));
    ctx.fillStyle = c.accent;
    ctx.fillRect(x, y, Math.max(0.5, cellW - 1), cellH - 1);
    ctx.globalAlpha = 1;
    hits.push({
      x,
      y,
      w: cellW,
      h: cellH,
      data: row,
      tip: (
        <>
          <strong>{`${row.sourceName} → ${row.targetName}`}</strong>
          {`${metric[1]}: ${format(row.value)}`}
          <br />
          {`${num(row.count, 0)} transfers`}
        </>
      ),
    });
  });
  ctx.fillStyle = c.muted;
  ctx.fillText(
    `${metric[1]} · grouped cell scale 0 — ${format(maximum)} · click for statistics`,
    8,
    height - 15,
  );
  return bindChart(g, hits, () => 0, {
    range: false,
    menu: false,
    onClick: (hit) => {
      if ("group" in hit.data) {
        inspectObject(`Transfer matrix · ${hit.data.axis.toLowerCase()} group`, hit.data.group);
      } else {
        inspectCell(hit.data);
      }
    },
  });
}
