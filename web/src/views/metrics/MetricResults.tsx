import { memo, useMemo, type Ref } from "react";
import { useMutation } from "@tanstack/react-query";
import { Chart } from "../../components/chart/Chart";
import { Card } from "../../components/panel/Card";
import { buttonControl } from "../../components/controls/factories";
import { StatGrid } from "../../components/ui/StatGrid";
import { AnalysisDiagnostics } from "../../components/ui/AnalysisDiagnostics";
import { DataTable } from "../../components/table/DataTable";
import { useExport } from "../../hooks/useExport";
import { scheduleRender, setView } from "../../state/viewActions";
import { updateState } from "../../state/store";
import { inspectContent, inspectObject } from "../../state/inspection";
import { notify } from "../../state/uiActions";
import { locName } from "../../state/selectors";
import { compact } from "../../lib/format/numbers";
import type { ViewState } from "../../state/types";
import { SERIES_COLUMNS } from "./columns";
import { evaluateMetric, errorMessage } from "./requests";
import { gridDescription, type MetricGrid } from "./metricGrid";
import { MetricPixelInspector } from "./MetricPixelInspector";
import { MetricStepInput } from "./MetricStepInput";
import type { MetricProgram, MetricResult } from "./types";

const OVERLAYS = [
  ["timeline", "Show with timeline", "timeline"],
  ["radar", "Show in radar", "radar"],
  ["counter", "Show in counters", "counters"],
] as const;
interface Props {
  result: MetricResult;
  program: MetricProgram;
  snapshot: ViewState;
  grid: MetricGrid;
  canvasRef: Ref<HTMLCanvasElement>;
  capture: () => MetricProgram;
}
export const MetricResults = memo(function MetricResults({
  result,
  program,
  snapshot,
  grid,
  canvasRef,
  capture,
}: Props) {
  const rows = useMemo(
    () =>
      result.series.flatMap((series) =>
        series.points.map(([time, value]) => ({
          location: series.location,
          name: series.name || locName(series.location),
          time,
          value,
          metric: program.name,
          unit: result.unit || result.metric.unit,
        })),
      ),
    [result, program.name],
  );
  useExport(rows, "custom-metric");
  const pixels = useMutation({
    mutationFn: () => evaluateMetric(program, grid, snapshot, undefined, true),
    onError: (error) => notify(errorMessage(error)),
  });
  const change = (action: () => void) => {
    try {
      capture();
      action();
    } catch (error) {
      notify(errorMessage(error));
    }
  };
  return (
    <>
      <StatGrid
        items={[
          { label: "Output series", value: compact(result.series.length) },
          { label: "Display samples", value: compact(rows.length) },
          { label: "Unit", value: result.unit || result.metric.unit || "dimensionless" },
          {
            label: "Location reduction",
            value: program.aggregation || "none",
            detail: program.scope || "all",
          },
        ]}
      />
      <Card
        title={program.name}
        controls={[
          buttonControl(
            "metric-pixels",
            "Inspect pixel attribution",
            () =>
              pixels.mutate(undefined, {
                onSuccess: (response) => {
                  const details = response.pixelDetails;
                  if (!details?.timelines.length)
                    return notify("No pixel evidence in this selection.");
                  inspectContent(
                    "Metric pixel evidence",
                    <MetricPixelInspector details={details} result={response} />,
                  );
                },
              }),
            { disabled: !grid.queryable || pixels.isPending },
          ),
          ...OVERLAYS.map(([id, label, view]) =>
            buttonControl(`metric-to-${id}`, label, () =>
              change(() => {
                updateState({ metricOverlay: true });
                setView(view);
              }),
            ),
          ),
        ]}
        caption={
          <>
            <MetricStepInput
              value={snapshot.metricStepSize}
              onChange={(value) =>
                change(() => {
                  updateState({ metricStepSize: value });
                  scheduleRender();
                })
              }
            />
            <span id="metric-grid-description">{gridDescription(grid)}</span>
          </>
        }
      >
        <div className="chart-wrap">
          <Chart
            canvasRef={canvasRef}
            id="studio-chart"
            aria-label="Custom metric result timeline"
            spec={{ type: "lines", data: result }}
          />
        </div>
      </Card>
      <AnalysisDiagnostics data={result} />
      <Card title="Reduced stream statistics">
        <DataTable
          id="studio-table"
          rows={result.series}
          columns={SERIES_COLUMNS}
          onRow={(row) => inspectObject("Analysis evidence", row)}
        />
      </Card>
    </>
  );
});
