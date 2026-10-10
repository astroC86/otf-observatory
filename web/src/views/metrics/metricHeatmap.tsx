import { canvas } from "../../charts/canvas";
import { axes } from "../../charts/axes";
import { bindChart } from "../../charts/interactions";
import type { ChartHit } from "../../charts/types";
import { duration } from "../../lib/format/time";
import { num } from "../../lib/format/numbers";
import { locName } from "../../state/selectors";
import { inspectObject } from "../../state/inspection";
import { setRange } from "../../state/rangeActions";
import type { ViewState } from "../../state/types";
import type { MetricResult } from "./types";

interface MetricCell {
  location: string;
  start: number;
  end: number;
  value: number;
}
export function metricHeatmap(
  element: HTMLCanvasElement,
  result: MetricResult,
  snapshot: ViewState,
) {
  const series = result.series.slice(0, 32);
  const graph = canvas(element, Math.max(180, series.length * 29 + 65));
  const { ctx, w, c } = graph;
  const left = Math.min(205, w * 0.25);
  const x = axes(graph, snapshot.start, snapshot.end, left, 32, 20);
  const hits: ChartHit<MetricCell>[] = [];
  const min = series.reduce((value, stream) => Math.min(value, stream.min ?? Infinity), Infinity);
  const max = series.reduce((value, stream) => Math.max(value, stream.max ?? -Infinity), -Infinity);
  series.forEach((stream, index) => {
    const y = 35 + index * 29;
    ctx.fillStyle = c.muted;
    ctx.font = "10px system-ui,sans-serif";
    ctx.save();
    ctx.beginPath();
    ctx.rect(5, y, left - 12, 24);
    ctx.clip();
    ctx.fillText(stream.name || locName(stream.location), 7, y + 16);
    ctx.restore();
    stream.points.forEach(([time, value], point) => {
      const next = stream.points[point + 1]?.[0] ?? snapshot.end;
      const a = x(time),
        b = x(next);
      if (value == null) return;
      const fraction = max === min ? 0.5 : (value - min) / (max - min);
      ctx.fillStyle = `hsl(${220 - fraction * 190} 65% ${88 - fraction * 45}%)`;
      ctx.fillRect(a, y, Math.max(0.7, b - a), 24);
      hits.push({
        x: a,
        y,
        w: Math.max(1, b - a),
        h: 24,
        data: { location: stream.location, start: time, end: next, value },
        tip: (
          <>
            <strong>{stream.name || locName(stream.location)}</strong>
            {`${duration(time)} · ${num(value, 6)} ${result.unit || result.metric.unit}`}
          </>
        ),
      });
    });
  });
  bindChart(
    graph,
    hits,
    (pixel) =>
      snapshot.start + ((pixel - left) / (w - left - 15)) * (snapshot.end - snapshot.start),
    {
      menu: false,
      onClick: (hit) =>
        inspectObject("Analysis evidence", hit.data, {
          after:
            hit.data.end > hit.data.start ? (
              <button
                id="analysis-zoom"
                className="primary"
                onClick={() => setRange(hit.data.start, hit.data.end)}
              >
                Zoom to this interval
              </button>
            ) : null,
        }),
    },
  );
}
