import { drawTimeline } from "./timeline";
import { drawBars } from "./bars";
import { drawMatrix } from "./matrix";
import { drawFlame } from "./flame";
import { drawProcesses } from "./processes";
import { drawLines } from "./lines";
import { drawResources } from "./resources";
import { drawOverview } from "./overview";
import { drawRelationships } from "./relationships";
import type { ChartSpec } from "./specs";

export function drawChart(element: HTMLCanvasElement, spec: ChartSpec) {
  switch (spec.type) {
    case "timeline":
      return drawTimeline(
        element,
        spec.data,
        spec.visible,
        spec.detail,
        spec.messages,
        spec.options,
      );
    case "bars":
      return drawBars(element, spec.data, spec.key, spec.height, spec.options);
    case "matrix":
      return drawMatrix(element, spec.data, spec.compact, spec.options);
    case "flame":
      return drawFlame(element, spec.data, spec.options);
    case "processes":
      return drawProcesses(element, spec.data, spec.options);
    case "lines":
      return drawLines(element, spec.data, spec.height, spec.options);
    case "resources":
      return drawResources(element, spec.data, spec.options);
    case "relationships":
      return drawRelationships(element, spec);
    case "overview":
      return drawOverview(element);
    case "custom":
      return spec.draw(element);
  }
}
