import type { ChartCanvas } from "./types";
import { disposeCanvas } from "./interactions";

export function canvas(element: HTMLCanvasElement, height: number): ChartCanvas {
  disposeCanvas(element);
  const w = Math.max(300, Math.floor(element.getBoundingClientRect().width)),
    dpr = window.devicePixelRatio || 1;
  element.style.height = height + "px";
  element.width = Math.round(w * dpr);
  element.height = Math.round(height * dpr);
  const ctx = element.getContext("2d");
  if (!ctx) throw new Error("Canvas 2D context is unavailable.");
  ctx.scale(dpr, dpr);
  const css = getComputedStyle(element);
  const c = {
    text: css.getPropertyValue("--text").trim(),
    muted: css.getPropertyValue("--muted").trim(),
    grid: css.getPropertyValue("--grid").trim(),
    panel: css.getPropertyValue("--panel").trim(),
    accent: css.getPropertyValue("--accent").trim(),
  };
  ctx.fillStyle = c.panel;
  ctx.fillRect(0, 0, w, height);
  ctx.font = "11px ui-monospace,monospace";
  return {
    el: element,
    ctx,
    w,
    h: height,
    c,
    dark: css.colorScheme === "dark",
  };
}

// Begins a clipped save frame; the caller restores after drawing.
export function clipRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
): void {
  ctx.save();
  ctx.beginPath();
  ctx.rect(x, y, width, height);
  ctx.clip();
}

export function strokeLine(
  ctx: CanvasRenderingContext2D,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): void {
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
}
