import { canvas } from "./canvas";
import { axes } from "./axes";
import { bindChart } from "./interactions";
import { drawLocationLabel } from "./locationLabel";
import type { ChartHit } from "./types";
import { palette } from "../lib/color/palette";
import { esc } from "../lib/escape";
import { duration } from "../lib/format/time";
import { locName } from "../state/selectors";
import { getState } from "../state/store";
import { EMPTY_RECORDS, type RelationshipRecord } from "../views/dependencies/types";

const CONDITIONAL = /inferred|conditional|candidate/;
const DASHED = [4, 3];
const SOLID: number[] = [];
export interface RelationshipChartData {
  intervals: readonly RelationshipRecord[];
  edges?: readonly RelationshipRecord[];
  nodes?: readonly RelationshipRecord[];
  wait?: boolean;
  page?: number;
  onEvidence: (row: RelationshipRecord) => void;
}

export function drawRelationships(
  element: HTMLCanvasElement,
  {
    intervals,
    edges = EMPTY_RECORDS,
    nodes = EMPTY_RECORDS,
    wait = false,
    page = 0,
    onEvidence,
  }: RelationshipChartData,
) {
  const { meta, start: viewStart, end: viewEnd } = getState();
  // Lanes follow the trace's location order (as in the timeline), not first appearance.
  const order = new Map(
    (meta?.locations ?? []).map((location, index) => [String(location.id), index]),
  );
  const locations = [
    ...new Set([...intervals, ...nodes].map((row) => String(row.location ?? "unknown"))),
  ].toSorted((a, b) => (order.get(a) ?? order.size) - (order.get(b) ?? order.size));
  const visible = locations.slice(page * 24, (page + 1) * 24);
  const lanes = new Map(visible.map((location, index) => [location, index]));
  const g = canvas(element, Math.max(180, visible.length * 42 + 65));
  const { ctx, w, c } = g;
  const left = Math.min(220, Math.max(120, w * 0.26));
  const x = axes(g, viewStart, viewEnd, left, 32, 22);
  const hits: ChartHit<RelationshipRecord>[] = [];
  ctx.font = "10px system-ui,sans-serif";
  visible.forEach((location, index) => {
    const y = 34 + index * 42;
    ctx.fillStyle = index % 2 ? c.grid + "60" : c.panel;
    ctx.fillRect(0, y, w, 42);
    drawLocationLabel(g, location, 9, y, left - 19, 42);
  });
  ctx.save();
  ctx.beginPath();
  ctx.rect(left, 32, w - left - 15, g.h - 53);
  ctx.clip();
  for (const row of intervals) {
    const lane = lanes.get(String(row.location ?? "unknown"));
    if (lane === undefined) continue;
    const start = Number(row.start);
    const a = x(Math.max(viewStart, start));
    const b = x(Math.min(viewEnd, Number(row.end ?? row.start)));
    if (b < a) continue;
    const y = 40 + lane * 42;
    const kind = row.kind || row.category || "interval";
    const index = [...kind].reduce((sum, char) => sum + char.charCodeAt(0), 0);
    ctx.fillStyle = wait ? "#8799b455" : palette[index % palette.length]!;
    ctx.globalAlpha = row.status === "incomplete" ? 0.55 : 0.85;
    ctx.fillRect(a, y, Math.max(2, b - a), 25);
    ctx.globalAlpha = 1;
    if (wait && row.causes?.length) {
      for (const cause of row.causes) {
        const interval = cause.dependency;
        if (!interval || interval.duration <= 0) continue;
        const required = cause.relation === "required-precondition";
        const begin = x(Math.max(viewStart, start, interval.start));
        const end = x(Math.min(viewEnd, Number(row.end), interval.end));
        if (end <= begin) continue;
        ctx.fillStyle = required ? "#3a83ce" : "#d78638";
        ctx.fillRect(begin, y + (required ? 5 : 14), Math.max(1, end - begin), 6);
      }
    } else if (wait && (row.inferred ?? 0) > 0) {
      const width = ((row.inferred ?? 0) / Math.max(1e-30, Number(row.end) - start)) * (b - a);
      ctx.fillStyle = "#d78638";
      ctx.fillRect(a, y + 7, Math.max(1, Math.min(b - a, width)), 11);
    }
    if (b - a > 75) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(a + 3, y, b - a - 6, 25);
      ctx.clip();
      ctx.fillStyle = wait ? c.text : "#fff";
      ctx.fillText(row.label || row.routine || kind, a + 5, y + 16);
      ctx.restore();
    }
    hits.push({
      x: a,
      y,
      w: Math.max(3, b - a),
      h: 25,
      data: row,
      tip: `<strong>${esc(row.label || row.routine || kind)}</strong>${esc(locName(row.location))}<br>${duration(row.start)} → ${duration(row.end)}<br>${esc(row.confidence || row.status || "recorded interval")}${wait ? `<br>Routine: ${duration(row.observed)} · estimated delay: ${duration(row.inferred)}` : ""}`,
    });
  }
  const lookup = new Map(nodes.map((node) => [String(node.id), node]));
  for (const edge of edges.slice(0, 3000)) {
    const source = lookup.get(String(edge.source));
    const target = lookup.get(String(edge.target));
    if (!source || !target) continue;
    const i = lanes.get(String(source.location));
    const j = lanes.get(String(target.location));
    if (i === undefined || j === undefined) continue;
    // An edge records its own endpoint times (e.g. stream order runs from the previous item's
    // end to the next item's start); a node marks an item's start and is shared by many edges.
    const x1 = x(Number(edge.start ?? source.time));
    const x2 = x(Number(edge.end ?? target.time));
    const y1 = 51 + i * 42;
    const y2 = 51 + j * 42;
    if (!Number.isFinite(x1 + x2)) continue;
    const conditional = CONDITIONAL.test(String(edge.confidence));
    ctx.strokeStyle = conditional ? "#d7863899" : c.text + "99";
    ctx.lineWidth = 1;
    ctx.setLineDash(conditional ? DASHED : SOLID);
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
    ctx.setLineDash(SOLID);
    const angle = Math.atan2(y2 - y1, x2 - x1);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.beginPath();
    ctx.moveTo(x2, y2);
    ctx.lineTo(x2 - 6 * Math.cos(angle - 0.4), y2 - 6 * Math.sin(angle - 0.4));
    ctx.lineTo(x2 - 6 * Math.cos(angle + 0.4), y2 - 6 * Math.sin(angle + 0.4));
    ctx.fill();
  }
  for (const node of nodes) {
    const lane = lanes.get(String(node.location));
    if (lane === undefined || node.time == null) continue;
    const px = x(node.time);
    const py = 52 + lane * 42;
    ctx.fillStyle = c.accent;
    ctx.beginPath();
    ctx.arc(px, py, 2.5, 0, Math.PI * 2);
    ctx.fill();
    hits.push({
      x: px - 4,
      y: py - 6,
      w: 8,
      h: 12,
      data: node,
      tip: `<strong>${esc(node.label || node.kind)}</strong>${duration(node.time)} · ${esc(locName(node.location))}`,
    });
  }
  ctx.restore();
  if (!visible.length) {
    ctx.fillStyle = c.muted;
    ctx.fillText("No recorded relationships in this selection.", 18, 68);
  }
  return bindChart(
    g,
    hits,
    (position) => viewStart + ((position - left) / (w - left - 15)) * (viewEnd - viewStart),
    { menu: false, onClick: (hit) => onEvidence(hit.data) },
  );
}
