import { canvas } from "../../charts/canvas";
import { axes } from "../../charts/axes";
import { bindChart } from "../../charts/interactions";
import type { ChartHit } from "../../charts/types";
import { palette } from "../../lib/color/palette";
import { duration } from "../../lib/format/time";
import { inspectObject } from "../../state/inspection";
import { setMarkerWindow } from "./actions";
import type { MarkerRegion, MarkerResult, MarkerSession } from "./types";

interface MarkerHit extends MarkerRegion {
  recordedStart: number;
  recordedEnd: number;
  trace: string;
  traceName: string;
}

export function drawMarkerTimeline(
  element: HTMLCanvasElement,
  data: MarkerResult,
  session: MarkerSession,
) {
  const g = canvas(element, 82 + data.runs.length * 56);
  const { ctx, w, c } = g;
  const left = Math.min(260, Math.max(150, w * 0.25));
  const x = axes(g, data.range.start, data.range.end, left, 28, 24);
  const hits: ChartHit<MarkerHit>[] = [];
  data.runs.forEach((run, index) => {
    const y = 39 + index * 56;
    const selected = session.runs.find((item) => item.id === run.id);
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, y - 6, left - 12, 43);
    ctx.clip();
    ctx.fillStyle = c.text;
    ctx.font = "11px system-ui,sans-serif";
    ctx.fillText(`${index ? `Run ${index}` : "Baseline"}: ${run.name}`, 8, y + 4);
    ctx.fillStyle = c.muted;
    ctx.font = "10px system-ui,sans-serif";
    ctx.fillText(
      run.locations.find((location) => location.id === run.location)?.name ||
        "No execution location",
      8,
      y + 21,
    );
    ctx.restore();
    ctx.fillStyle = c.grid;
    ctx.fillRect(left, y - 7, w - left - 15, 30);
    for (const region of run.timeline.rows) {
      const a = Math.max(left, x(region.displayStart));
      const b = Math.min(w - 15, x(region.displayEnd));
      if (b <= a) continue;
      let hash = 0;
      for (const ch of region.name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
      ctx.fillStyle = palette[hash % palette.length]!;
      ctx.fillRect(a, y - 5, Math.max(0.7, b - a), 26);
      hits.push({
        x: a,
        y: y - 5,
        w: Math.max(1, b - a),
        h: 26,
        data: {
          ...region,
          recordedStart: region.start,
          recordedEnd: region.end,
          start: region.displayStart,
          end: region.displayEnd,
          trace: run.id,
          traceName: run.name,
        },
        tip: (
          <>
            <strong>{region.name}</strong>
            {run.name}
            <br />
            {`Recorded ${duration(region.start)}–${duration(region.end)}`}
            <br />
            {`Display ${duration(region.displayStart)}–${duration(region.displayEnd)}`}
            {region.coalesced ? (
              <>
                <br />
                Subpixel calls coalesced
              </>
            ) : null}
          </>
        ),
      });
    }
    if (selected?.time != null) {
      const px = x(selected.time + run.offset);
      if (px >= left && px <= w - 15) {
        ctx.strokeStyle = c.text;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(px, y - 11);
        ctx.lineTo(px, y + 25);
        ctx.stroke();
      }
    }
  });
  return bindChart(
    g,
    hits,
    (px) =>
      data.range.start + ((px - left) / (w - left - 15)) * (data.range.end - data.range.start),
    {
      menu: false,
      rangeState: () => data.range,
      onRange: setMarkerWindow,
      onClick: (hit) => inspectObject("Aligned recorded interval", hit.data),
    },
  );
}
