import { useLayoutEffect, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Chart } from "../../components/chart/Chart";
import { Card } from "../../components/panel/Card";
import { queryKeys } from "../../api/queryKeys";
import { queryClient } from "../../api/queryClient";
import { useEmbedHidden } from "../../embed/useEmbedHidden";
import { updateState } from "../../state/store";
import { beginViewWork, scheduleRender, setView } from "../../state/viewActions";
import type { ViewState } from "../../state/types";
import { readProgram } from "./program";
import { evaluateMetric } from "./requests";
import { gridDescription, type MetricChartMode } from "./metricGrid";
import { metricHeatmap } from "./metricHeatmap";
import { MetricStepInput } from "./MetricStepInput";
import { useMetricGrid } from "./useMetricGrid";

const attemptedSelections = new WeakSet<ViewState>();

export function MetricOverlay({ mode, snapshot }: { mode: MetricChartMode; snapshot: ViewState }) {
  const program = useMemo(
    () => readProgram(snapshot.metricProgram, snapshot.meta),
    [snapshot.metricProgram, snapshot.meta],
  );
  const { grid, canvasRef } = useMetricGrid(snapshot.metricStepSize, mode, scheduleRender);
  const hidden = useEmbedHidden() || undefined;
  const queryKey = [
    ...queryKeys.view(snapshot),
    "metric-overlay",
    program,
    grid?.bins,
    grid?.queryable,
  ];
  const enabled = snapshot.metricOverlay && !!grid;
  const firstAttempt = !attemptedSelections.has(snapshot);
  if (enabled) attemptedSelections.add(snapshot);
  // A failed suspended update must settle into its error UI, not start another fetch.
  const failed = !firstAttempt && queryClient.getQueryState(queryKey)?.status === "error";
  const response = useQuery({
    queryKey,
    enabled: enabled && !failed,
    queryFn: ({ signal }) => evaluateMetric(program, grid!, snapshot, signal),
  });
  const finish = useRef<(() => void) | undefined>(undefined);
  useLayoutEffect(() => {
    if (!snapshot.metricOverlay) return;
    if (!snapshot.metricProgram) updateState({ metricProgram: program });
    finish.current = beginViewWork(snapshot.epoch);
    return () => finish.current?.();
  }, [snapshot.epoch]);
  useLayoutEffect(() => {
    if (!response.isPending) finish.current?.();
  }, [snapshot.epoch, response.isPending, snapshot.metricOverlay]);
  const result = response.data;
  const displayed = useRef(false);
  if (result) displayed.current = true;
  if (snapshot.metricOverlay && grid && response.isPending && displayed.current)
    throw queryClient.fetchQuery({
      queryKey,
      queryFn: ({ signal }) => evaluateMetric(program, grid, snapshot, signal),
    });
  return (
    <>
      {response.error ? (
        <p className="analysis-warning" data-embed-hidden={hidden}>
          {response.error.message}
        </p>
      ) : null}
      <div className="metric-overlay-control filter-line" data-embed-hidden={hidden}>
        <button id="open-metric-studio" onClick={() => setView("metrics")}>
          Metric studio
        </button>
        <label className="check">
          <input
            id="custom-metric-overlay"
            type="checkbox"
            checked={snapshot.metricOverlay}
            onChange={(event) => {
              updateState({ metricOverlay: event.currentTarget.checked });
              scheduleRender();
            }}
          />
          {mode === "radar" ? "Custom metric radar" : "Custom metric timeline"}
        </label>
        <span className="muted">
          {String(
            snapshot.metricProgram?.name ||
              "Compose metrics from counters, functions, I/O and messages",
          )}
        </span>
      </div>
      {snapshot.metricOverlay ? (
        <div>
          <Card
            title={program.name}
            tools={
              <MetricStepInput
                value={snapshot.metricStepSize}
                onChange={(value) => {
                  if (result) {
                    updateState({ metricStepSize: value });
                    scheduleRender();
                  }
                }}
              />
            }
            caption={
              <span id="metric-grid-description">
                {result && grid
                  ? `${gridDescription(grid)} · ${mode === "radar" ? "First 32 evaluated streams." : "Linked to the selected time range."} ${result.unit || result.metric.unit || ""}`
                  : ""}
              </span>
            }
          >
            <div className="chart-wrap">
              {result ? (
                mode === "radar" ? (
                  <Chart
                    canvasRef={canvasRef}
                    id="metric-overlay-chart"
                    aria-label="Custom metric overlay"
                    draw={(element) => metricHeatmap(element, result, snapshot)}
                  />
                ) : (
                  <Chart
                    canvasRef={canvasRef}
                    id="metric-overlay-chart"
                    aria-label="Custom metric overlay"
                    spec={{ type: "lines", data: result, height: 230 }}
                  />
                )
              ) : (
                <canvas
                  ref={canvasRef}
                  id="metric-overlay-chart"
                  className="chart"
                  aria-label="Custom metric overlay"
                />
              )}
            </div>
          </Card>
        </div>
      ) : null}
    </>
  );
}
