import { getState } from "../state/store";
import { shortLoc, locName } from "../state/selectors";
import { num, compact } from "../lib/format/numbers";
import { bytes } from "../lib/format/bytes";
import { duration } from "../lib/format/time";
import { esc } from "../lib/escape";
import { inspectObject } from "../state/inspection";
import { canvas } from "./canvas";
import { bindChart } from "./interactions";
import type { MatrixChartMetric, MatrixChartRow, ChartHit, ChartOptions } from "./types";

interface MatrixBucket extends Record<MatrixChartMetric | "matched" | "weighted", number> {
  source: string;
  target: string;
}

function matrixLocations(rows: readonly MatrixChartRow[]): string[] {
  return [
    ...new Set(rows.flatMap((r) => [r.source, r.target]).filter((id) => id != null)),
  ].toSorted((a, b) => Number(a) - Number(b));
}

export function drawMatrix(
  element: HTMLCanvasElement,
  rows: readonly MatrixChartRow[],
  compactView = false,
  options: ChartOptions<MatrixChartRow> = {},
): void {
  const allIds = matrixLocations(rows);
  let labels: Record<string, string> | null = null;
  if (allIds.length > 48) {
    const block = Math.ceil(allIds.length / 48),
      indices = new Map(allIds.map((v, i) => [v, Math.floor(i / block)])),
      buckets = new Map<string, MatrixBucket>();
    labels = {};
    for (let i = 0; i < Math.ceil(allIds.length / block); i++)
      labels[String(i)] = `Locations ${i * block + 1}–${Math.min(allIds.length, (i + 1) * block)}`;
    for (const r of rows) {
      if (r.source == null || r.target == null) continue;
      const source = String(indices.get(r.source)),
        target = String(indices.get(r.target)),
        key = source + "|" + target;
      let b = buckets.get(key);
      if (!b) {
        b = {
          source,
          target,
          count: 0,
          bytes: 0,
          matched: 0,
          weighted: 0,
          duration: 0,
        };
        buckets.set(key, b);
      }
      b.count += r.count;
      b.bytes += r.bytes;
      b.matched += r.matched;
      b.weighted += (r.duration || 0) * r.matched;
    }
    rows = [...buckets.values()].map((r) => ({
      ...r,
      duration: r.matched ? r.weighted / r.matched : 0,
    }));
  }
  const g = canvas(element, compactView ? 260 : 440),
    { ctx, w, h, c } = g;
  const metric = getState().matrixMetric as MatrixChartMetric;
  const ids = matrixLocations(rows);
  if (!ids.length) {
    ctx.fillStyle = c.muted;
    ctx.fillText("No MPI messages in this interval.", 20, 50);
    return;
  }
  const left = compactView ? 55 : 95,
    top = 35,
    size = Math.min(h - top - 25, w - left - 75),
    n = ids.length,
    cell = size / Math.max(n, 1),
    max = rows.reduce((m, r) => Math.max(m, r[metric] || 0), 1e-30),
    lookup = new Map(rows.map((r) => [r.source + "|" + r.target, r])),
    hits: ChartHit<MatrixChartRow>[] = [];
  ctx.font = "10px ui-monospace,monospace";
  ctx.fillStyle = c.muted;
  ctx.fillText("RECEIVER →", left, 14);
  ctx.fillText("SENDER", 5, top - 5);
  for (const [i, id] of ids.entries()) {
    if (n <= 32 || i % Math.ceil(n / 32) === 0) {
      ctx.fillStyle = c.muted;
      ctx.fillText(id.length > 5 ? String(i) : id, left + i * cell + 2, top - 7);
      ctx.fillText(id.length > 5 ? String(i) : id, left - 30, top + i * cell + cell * 0.65);
    }
    for (let j = 0; j < n; j++) {
      const r = lookup.get(ids[i] + "|" + ids[j]);
      const v = r?.[metric] || 0;
      const intensity = v ? Math.sqrt(v / max) : 0;
      ctx.fillStyle = v ? `hsl(211 66% ${87 - intensity * 48}%)` : c.grid;
      ctx.fillRect(
        left + j * cell + 1,
        top + i * cell + 1,
        Math.max(0.8, cell - 2),
        Math.max(0.8, cell - 2),
      );
      if (r)
        hits.push({
          x: left + j * cell,
          y: top + i * cell,
          w: cell,
          h: cell,
          data: r,
          tip: `<strong>${esc(labels?.[String(r.source)] || shortLoc(r.source))} → ${esc(labels?.[String(r.target)] || shortLoc(r.target))}</strong>${num(r.count, 0)} messages · ${bytes(r.bytes)}<br>Mean transfer: ${duration(r.duration)}`,
        });
    }
  }
  const gradient = ctx.createLinearGradient(0, top + size, 0, top);
  gradient.addColorStop(0, "hsl(211 66% 87%)");
  gradient.addColorStop(1, "hsl(211 66% 39%)");
  ctx.fillStyle = gradient;
  ctx.fillRect(left + size + 18, top, 10, size);
  ctx.fillStyle = c.muted;
  ctx.font = "9px ui-monospace,monospace";
  ctx.fillText(
    getState().matrixMetric === "bytes"
      ? bytes(max)
      : getState().matrixMetric === "count"
        ? compact(max)
        : duration(max),
    left + size + 12,
    top - 8,
  );
  ctx.fillText("0", left + size + 20, top + size + 14);
  bindChart(g, hits, () => 0, {
    range: false,
    menu: false,
    onClick: (h) =>
      inspectObject("Communication pair", {
        ...h.data,
        source: labels?.[String(h.data.source)] || locName(h.data.source),
        target: labels?.[String(h.data.target)] || locName(h.data.target),
      }),
    ...options,
  });
}
