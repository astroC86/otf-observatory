import { duration } from "../lib/format/time";
import { getState } from "../state/store";
import { strokeLine } from "./canvas";
import type { ChartCanvas } from "./types";

export function axes(
  g: ChartCanvas,
  start: number,
  end: number,
  left = 150,
  top = 32,
  bottom = 22,
): (time: number) => number {
  const { ctx, w, h, c } = g;
  ctx.strokeStyle = c.grid;
  ctx.lineWidth = 1;
  ctx.fillStyle = c.muted;
  ctx.font = "10px ui-monospace,monospace";
  const count = Math.max(2, Math.floor((w - left) / 150));
  const lastLabel = duration(start + ((end - start) * count) / count);
  const lastWidth = ctx.measureText(lastLabel).width;
  const lastLeft = left + ((w - left - 15) * count) / count - lastWidth;
  let labelRight = -Infinity;
  for (let i = 0; i <= count; i++) {
    const x = left + ((w - left - 15) * i) / count;
    strokeLine(ctx, x, top, x, h - bottom);
    ctx.textAlign = i === count ? "right" : "left";
    const label = i === count ? lastLabel : duration(start + ((end - start) * i) / count);
    const width = i === count ? lastWidth : ctx.measureText(label).width;
    const labelLeft = i === count ? x - width : x;
    if (labelLeft >= labelRight + 1 && (i === count || labelLeft + width <= lastLeft - 1)) {
      ctx.fillText(label, x, 17);
      labelRight = labelLeft + width;
    }
  }
  ctx.textAlign = "left";
  return (t) => left + ((t - start) / (end - start || 1)) * (w - left - 15);
}

export function timeAt(g: ChartCanvas, left: number): (position: number) => number {
  return (px) =>
    getState().start + ((px - left) / (g.w - left - 15)) * (getState().end - getState().start);
}
