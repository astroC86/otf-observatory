import { locations, groups } from "../state/selectors";
import { clipRect } from "./canvas";
import type { ChartCanvas } from "./types";

export function drawLocationLabel(
  g: ChartCanvas,
  id: string | number | null | undefined,
  x: number,
  y: number,
  width: number,
  height: number,
): void {
  const { ctx, c } = g,
    l = id == null ? undefined : locations[id];
  const process = l ? groups[l.group]?.name || `Process ${l.group}` : "";
  const name = l?.name || String(id ?? "Unresolved");
  const fit = (text: string): string => {
    if (ctx.measureText(text).width <= width) return text;
    let head = Math.ceil(text.length / 2),
      tail = Math.floor(text.length / 2);
    while (head + tail > 0) {
      const value = text.slice(0, head) + "…" + (tail ? text.slice(-tail) : "");
      if (ctx.measureText(value).width <= width) return value;
      if (head > tail) head--;
      else tail--;
    }
    return "…";
  };
  clipRect(ctx, x, y, width, height);
  ctx.textBaseline = "middle";
  const center = y + height / 2;
  if (process && process !== name) {
    ctx.fillStyle = c.muted;
    ctx.font = "10px system-ui,sans-serif";
    ctx.fillText(fit(process), x, center - 6.5);
  }
  ctx.fillStyle = c.text;
  ctx.font = "11px system-ui,sans-serif";
  ctx.fillText(fit(name), x, center + (process && process !== name ? 6.5 : 0));
  ctx.restore();
}
