import { duration } from "../../lib/format/time";
import { esc } from "../../lib/escape";
import { num } from "../../lib/format/numbers";
import { setRange } from "../../state/rangeActions";
import { setView } from "../../state/viewActions";
import { shortLoc } from "../../state/selectors";
import { updateState } from "../../state/store";
import { axes } from "../../charts/axes";
import { bindChart } from "../../charts/interactions";
import { canvas } from "../../charts/canvas";
import { drawLocationLabel } from "../../charts/locationLabel";
import type { ChartHit } from "../../charts/types";
import type { ViewState } from "../../state/types";
import type { OverviewResponse } from "../../api/types/execution";

interface RadarCell {
  location: string;
  start: number;
  end: number;
}
export function drawRadar(
  element: HTMLCanvasElement,
  data: OverviewResponse,
  locations: readonly string[],
  group: string,
  state: ViewState,
) {
  const rowHeight = 25;
  const graph = canvas(element, Math.max(160, locations.length * rowHeight + 62));
  const { ctx, w, c } = graph;
  const left = 160;
  const x = axes(graph, state.start, state.end, left, 32, 20);
  const hits: ChartHit<RadarCell>[] = [];
  locations.forEach((location, row) => {
    const y = 35 + row * rowHeight;
    ctx.fillStyle = c.muted;
    ctx.font = "10px system-ui,sans-serif";
    drawLocationLabel(graph, location, 8, y, left - 18, rowHeight);
    const values = data.series[location];
    const bins = values?.length ?? data.bins;
    for (let index = 0; index < bins; index++) {
      const value = values?.[index] ?? 0;
      const start = data.start + (index * (data.end - data.start)) / data.bins;
      const end = data.start + ((index + 1) * (data.end - data.start)) / data.bins;
      ctx.fillStyle = value ? `hsl(${215 - value * 180} 65% ${88 - value * 48}%)` : c.grid;
      ctx.fillRect(x(start), y, Math.max(1, x(end) - x(start) + 0.2), rowHeight - 4);
      hits.push({
        x: x(start),
        y,
        w: Math.max(1, x(end) - x(start)),
        h: rowHeight - 4,
        data: { location, start, end },
        tip: `<strong>${esc(shortLoc(location))}</strong>${esc(group || "Activity")}: ${num(value * 100, 2)}%<br>${duration(start)} → ${duration(end)}`,
      });
    }
  });
  return bindChart(
    graph,
    hits,
    (pixel) => state.start + ((pixel - left) / (w - left - 15)) * (state.end - state.start),
    {
      menu: false,
      rangeState: () => ({ start: state.start, end: state.end }),
      onClick: ({ data: cell }) => {
        updateState({ detailLocation: cell.location });
        setRange(cell.start, cell.end);
        setView("timeline");
      },
    },
  );
}
