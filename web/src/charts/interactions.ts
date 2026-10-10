import { getState } from "../state/store";
import type { ReactNode } from "react";
import { setRange, zoom } from "../state/rangeActions";
import { showMenu, setTooltip, setBrush } from "../state/inspection";
import type { ChartCanvas, ChartHit, ChartOptions, ChartPoint, ChartRange } from "./types";

const bindings = new WeakMap<HTMLCanvasElement, () => void>();
let tooltipOwner: HTMLCanvasElement | null = null;
let brushOwner: HTMLCanvasElement | null = null;

export function ownBinding(element: HTMLCanvasElement, cancel: () => void): () => void {
  bindings.set(element, cancel);
  return () => {
    if (bindings.get(element) === cancel) disposeCanvas(element);
  };
}

export function disposeCanvas(element: HTMLCanvasElement): void {
  const cancel = bindings.get(element);
  bindings.delete(element);
  cancel?.();
  element.onpointerdown = null;
  element.onpointermove = null;
  element.onpointerup = null;
  element.onpointerleave = null;
  element.onpointercancel = null;
  element.ondblclick = null;
  element.oncontextmenu = null;
  element.onwheel = null;
  element.style.cursor = "";
  if (tooltipOwner === element) {
    tooltipOwner = null;
    setTooltip({ clientX: 0, clientY: 0 }, null);
  }
  if (brushOwner === element) {
    brushOwner = null;
    setBrush(null);
  }
}

export const tooltip = setTooltip;

function hasRange(data: object): data is ChartRange {
  return (
    "start" in data &&
    typeof data.start === "number" &&
    "end" in data &&
    typeof data.end === "number"
  );
}

export function bindChart<T extends object>(
  g: ChartCanvas,
  hits: readonly ChartHit<T>[],
  toTime: (position: number) => number,
  {
    range = true,
    onClick,
    onDoubleClick,
    onHover,
    onBrush,
    menu = true,
    onRange = setRange,
    rangeState = getState,
  }: ChartOptions<T> = {},
): () => void {
  disposeCanvas(g.el);
  let down: (ChartPoint & ChartRange & { readonly shift: boolean }) | null = null,
    moved = false,
    brush = false,
    pointerId: number | null = null;
  const point = (e: MouseEvent): ChartPoint => ({
    x: e.clientX - g.el.getBoundingClientRect().left,
    y: e.clientY - g.el.getBoundingClientRect().top,
  });
  const hit = (p: ChartPoint): ChartHit<T> | null => {
    for (let i = hits.length - 1; i >= 0; i--) {
      const h = hits[i]!;
      if (p.x >= h.x && p.x <= h.x + h.w && p.y >= h.y && p.y <= h.y + h.h) return h;
    }
    return null;
  };
  const showTooltip = (event: PointerEvent, content: ReactNode): void => {
    tooltipOwner = content ? g.el : null;
    tooltip(event, content);
  };
  const clearBrush = (): void => {
    if (!brush) return;
    brush = false;
    if (brushOwner === g.el) {
      brushOwner = null;
      setBrush(null);
    }
    onBrush?.(null);
  };
  g.el.onpointerdown = (e) => {
    if (e.button !== 0) return;
    down = {
      ...point(e),
      start: rangeState().start,
      end: rangeState().end,
      shift: e.shiftKey,
    };
    moved = false;
    pointerId = e.pointerId;
    g.el.setPointerCapture(e.pointerId);
  };
  g.el.onpointermove = (e) => {
    const p = point(e);
    if (down && Math.abs(p.x - down.x) > 4) {
      moved = true;
      showTooltip(e, null);
      onHover?.(null, e);
      if (range && !down.shift) {
        const rect = g.el.getBoundingClientRect();
        const selection = {
          left: rect.left + Math.min(down.x, p.x),
          top: rect.top,
          width: Math.abs(p.x - down.x),
          height: rect.height,
        };
        brush = true;
        brushOwner = g.el;
        setBrush(selection);
        onBrush?.(selection);
      }
      g.el.style.cursor = down.shift ? "grabbing" : "crosshair";
    } else {
      const h = hit(p);
      const content = typeof h?.tip === "function" ? h.tip() : h?.tip;
      showTooltip(e, content || null);
      onHover?.(h, e);
      g.el.style.cursor = h ? "pointer" : "crosshair";
    }
  };
  g.el.onpointerup = (e) => {
    clearBrush();
    const p = point(e),
      h = hit(p);
    if (down && moved && range) {
      if (down.shift) {
        const delta = toTime(down.x) - toTime(p.x);
        onRange(down.start + delta, down.end + delta);
      } else {
        const a = toTime(down.x),
          b = toTime(p.x);
        onRange(Math.min(a, b), Math.max(a, b));
      }
    } else if (h && onClick) onClick(h);
    down = null;
    pointerId = null;
  };
  g.el.onpointerleave = (e) => {
    showTooltip(e, null);
    onHover?.(null, e);
  };
  g.el.ondblclick = (e) => {
    const h = hit(point(e));
    if (h && onDoubleClick) onDoubleClick(h);
    else if (h && hasRange(h.data)) onRange(h.data.start, h.data.end);
  };
  g.el.oncontextmenu = (e) => {
    if (!menu) return;
    e.preventDefault();
    const h = hit(point(e));
    if (h?.data) showMenu(e, h.data);
  };
  g.el.onwheel = (e) => {
    if (!e.ctrlKey && !e.altKey) return;
    e.preventDefault();
    if (onRange === setRange) zoom(e.deltaY > 0 ? 1.4 : 1 / 1.4);
    else {
      const current = rangeState(),
        center = (current.start + current.end) / 2,
        half = ((current.end - current.start) * (e.deltaY > 0 ? 1.4 : 1 / 1.4)) / 2;
      onRange(center - half, center + half);
    }
  };
  g.el.onpointercancel = () => {
    down = null;
    pointerId = null;
    clearBrush();
  };
  return ownBinding(g.el, () => {
    down = null;
    clearBrush();
    if (pointerId !== null && g.el.hasPointerCapture(pointerId))
      g.el.releasePointerCapture(pointerId);
    pointerId = null;
  });
}
