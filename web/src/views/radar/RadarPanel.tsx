import { useCallback, useMemo } from "react";
import { useExport } from "../../hooks/useExport";
import { Card } from "../../components/panel/Card";
import { Chart } from "../../components/chart/Chart";
import type { Option } from "../../components/controls/types";
import type { ViewState } from "../../state/types";
import type { OverviewResponse } from "../../api/types/execution";
import { change } from "../executionState";
import { drawRadar } from "./draw";
import { buttonControl, selectControl } from "../../components/controls/factories";

interface RadarPanelProps {
  data: OverviewResponse;
  locations: readonly string[];
  total: number;
  page: number;
  group: string;
  state: ViewState;
}
export function RadarPanel({ data, locations, total, page, group, state }: RadarPanelProps) {
  const rows = useMemo(
    () =>
      locations.flatMap((location) =>
        (data.series[location] || []).map((fraction, index) => ({
          location,
          start: data.start + (index * (data.end - data.start)) / data.bins,
          end: data.start + ((index + 1) * (data.end - data.start)) / data.bins,
          fraction,
        })),
      ),
    [data, locations],
  );
  const options = useMemo<readonly Option[]>(
    () => [
      ["", "All recorded activity"],
      ...new Set(state.meta.regions.map((region) => region.group)),
    ],
    [state.meta.regions],
  );
  const draw = useCallback(
    (element: HTMLCanvasElement) => drawRadar(element, data, locations, group, state),
    [data, locations, group, state],
  );
  useExport(rows, "activity-radar");
  return (
    <Card
      title="Activity radar"
      controls={[
        buttonControl(
          "radar-prev",
          "←",
          () => change((previous) => ({ radarPage: previous.radarPage - 1 })),
          {
            disabled: page === 0,
          },
        ),
        {
          kind: "content",
          children: (
            <span>{`${page * 32 + 1}–${Math.min(total, (page + 1) * 32)} / ${total}`}</span>
          ),
        },
        buttonControl(
          "radar-next",
          "→",
          () => change((previous) => ({ radarPage: previous.radarPage + 1 })),
          {
            disabled: (page + 1) * 32 >= total,
          },
        ),
        selectControl(
          "radar-group",
          undefined,
          group,
          options,
          (value) => change({ radarGroup: value }),
          {
            ariaLabel: "Radar function group",
          },
        ),
      ]}
      caption={
        <span>{`Cell intensity = fraction of the time bin spent in ${group || "recorded code"}. Drag to zoom; click a cell for its process timeline.`}</span>
      }
    >
      <div className="chart-wrap">
        <Chart id="radar-chart" aria-label="Time density heatmap by location" draw={draw} />
      </div>
    </Card>
  );
}
