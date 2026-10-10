import { canvas } from "../../charts/canvas";
import { bindChart } from "../../charts/interactions";
import type { ChartHit } from "../../charts/types";
import { duration } from "../../lib/format/time";
import { getState } from "../../state/store";
import { inspectEvidence } from "./actions";
import type { Alignment, AnchorMatch, Ensemble } from "./types";

function mappedTime(time: number, data: Alignment, mode: string) {
  const points = mode === "piecewise" ? data.piecewise || [] : [];
  if (points.length < 2) return data.shift + data.scale * time;
  const first = points[0]!,
    last = points[points.length - 1]!;
  if (time < first.b) return first.a + data.scale * (time - first.b);
  if (time > last.b) return last.a + data.scale * (time - last.b);
  let lo = 0,
    hi = points.length - 1;
  while (lo + 1 < hi) {
    const mid = (lo + hi) >> 1;
    if (points[mid]!.b <= time) lo = mid;
    else hi = mid;
  }
  const a = points[lo]!,
    b = points[hi]!;
  return a.a + ((time - a.b) / (b.b - a.b)) * (b.a - a.a);
}

export function drawAnchors(
  element: HTMLCanvasElement,
  data: Alignment | Ensemble,
  traceDuration = 0,
) {
  const many = "runs" in data;
  const runs = many ? data.runs : [{ name: "Comparison", alignment: data }];
  const g = canvas(element, many ? 95 + runs.length * 44 : 260);
  const { ctx, w, c } = g;
  const left = many ? Math.min(220, w * 0.28) : 90,
    right = w - (many ? 22 : 25),
    top = many ? 34 : 65;
  const range = many
    ? data.baseline.range
    : { start: 0, end: Math.max(traceDuration, ...data.matches.map((match) => match.timeA || 0)) };
  const width = many ? range.end - range.start || 1 : range.end;
  const x = (time: number) => left + ((time - range.start) / width) * (right - left);
  const hits: ChartHit<AnchorMatch & { run?: string }>[] = [];
  const mode = getState().ensembleMode;
  const track = (name: string, y: number) => {
    const max = Math.max(8, Math.floor((left - 20) / 6));
    ctx.fillStyle = c.muted;
    ctx.fillText(name.length > max ? name.slice(0, max - 1) + "…" : name, 8, y + 4);
    ctx.strokeStyle = c.grid;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  };
  ctx.font = "11px system-ui,sans-serif";
  track("Baseline", top);
  runs.forEach((run, index) => {
    const y = many ? 78 + index * 44 : 185;
    const maxB = many ? 1 : Math.max(1, ...run.alignment.matches.map((match) => match.timeB || 0));
    track(run.name, y);
    for (const match of run.alignment.matches.slice(0, 1500)) {
      const source = x(match.timeA);
      const aligned = many ? mappedTime(match.timeB, run.alignment, mode) : match.timeB;
      const target = many ? x(aligned) : left + (aligned / maxB) * (right - left);
      if (many && (target < left || target > right)) continue;
      if (many) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(left, 20, right - left, y + 10);
        ctx.clip();
      }
      ctx.strokeStyle = many ? "#4d91cf25" : "#4d91cf55";
      ctx.beginPath();
      ctx.moveTo(source, top);
      ctx.lineTo(target, y);
      ctx.stroke();
      ctx.fillStyle = many && match.explicit ? "#d59d48" : c.accent;
      ctx.fillRect(target - 1.5, y - (many ? 5 : 4), 3, many ? 10 : 8);
      if (many) ctx.restore();
      else ctx.fillRect(source - 1.5, top - 4, 3, 8);
      hits.push({
        x: (many ? target : source) - 4,
        y: many ? y - 8 : top - 9,
        w: 8,
        h: many ? 16 : 18,
        data: many ? { ...match, run: run.name } : match,
        tip: many ? (
          <>
            <strong>{run.name}</strong>
            {match.label}
            <br />
            {`Baseline ${duration(match.timeA)} · recorded ${duration(match.timeB)} · aligned ${duration(aligned)}`}
          </>
        ) : (
          <>
            <strong>{match.label}</strong>
            {`Baseline ${duration(match.timeA)} · other ${duration(match.timeB)}`}
            <br />
            {`Residual ${duration(match.residual)}`}
          </>
        ),
      });
    }
  });
  ctx.fillStyle = c.muted;
  if (many) {
    ctx.fillText(duration(range.start), left, 14);
    ctx.fillText(duration(range.end), Math.max(left, right - 65), 14);
  } else
    ctx.fillText("Anchor order is preserved. Each track uses its own full-run scale.", left, 235);
  return bindChart(g, hits, () => 0, {
    range: false,
    menu: false,
    onClick: (hit) => inspectEvidence(hit.data),
  });
}
