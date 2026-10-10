import { getState } from "../state/store";
import { getOverviewData, groupColor } from "../state/selectors";
import { setRange } from "../state/rangeActions";
import { canvas } from "./canvas";
import { disposeCanvas, ownBinding } from "./interactions";
import type { ChartCanvas } from "./types";

export function drawOverview(element: HTMLCanvasElement): void {
  const meta = getState().meta;
  if (!meta) {
    disposeCanvas(element);
    return;
  }
  const g = canvas(element, 44),
    { ctx, w, h, c } = g;
  const overviewData = getOverviewData();
  if (overviewData) {
    const entries = Object.entries(overviewData.series),
      max = Math.max(
        1,
        ...Array.from({ length: overviewData.bins }, (_, i) =>
          entries.reduce((sum, [, v]) => sum + v[i]!, 0),
        ),
      );
    for (let i = 0; i < overviewData.bins; i++) {
      let y = h - 2;
      for (const [key, values] of entries) {
        const height = (values[i]! / max) * (h - 5);
        ctx.fillStyle = groupColor(key);
        ctx.fillRect((i * w) / overviewData.bins, y - height, w / overviewData.bins + 0.4, height);
        y -= height;
      }
    }
  }
  const a = (getState().start / meta.duration) * w,
    b = (getState().end / meta.duration) * w;
  ctx.fillStyle = g.dark ? "#101923aa" : "#ffffffb5";
  ctx.fillRect(0, 0, a, h);
  ctx.fillRect(b, 0, w - b, h);
  ctx.strokeStyle = c.accent;
  ctx.lineWidth = 1.5;
  ctx.strokeRect(a + 0.75, 1, Math.max(1, b - a - 1.5), h - 2);
  ctx.fillStyle = c.accent;
  ctx.fillRect(a, 12, 3, 20);
  ctx.fillRect(b - 3, 12, 3, 20);
  bindOverview(g, meta.duration);
}

export function bindOverview(g: ChartCanvas, totalDuration: number): () => void {
  disposeCanvas(g.el);
  let start: number | null = null,
    pointerId: number | null = null;
  g.el.onpointerdown = (e) => {
    start = e.offsetX;
    pointerId = e.pointerId;
    g.el.setPointerCapture(e.pointerId);
  };
  g.el.onpointerup = (e) => {
    if (start !== null && Math.abs(e.offsetX - start) > 4)
      setRange(
        (Math.min(start, e.offsetX) / g.w) * totalDuration,
        (Math.max(start, e.offsetX) / g.w) * totalDuration,
      );
    start = null;
    pointerId = null;
  };
  g.el.ondblclick = () => setRange(0, totalDuration);
  g.el.onpointercancel = () => {
    start = null;
    pointerId = null;
  };
  return ownBinding(g.el, () => {
    start = null;
    if (pointerId !== null && g.el.hasPointerCapture(pointerId))
      g.el.releasePointerCapture(pointerId);
    pointerId = null;
  });
}
