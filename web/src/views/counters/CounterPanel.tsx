import { useLayoutEffect, useMemo, useRef } from "react";
import { inspectObject } from "../../state/inspection";
import { locName } from "../../state/selectors";
import { palette } from "../../lib/color/palette";
import { useExport } from "../../hooks/useExport";
import { Card } from "../../components/panel/Card";
import { Chart } from "../../components/chart/Chart";
import { ControlBar } from "../../components/controls/ControlBar";
import { DataTable } from "../../components/table/DataTable";
import type { Option } from "../../components/controls/types";
import type { ViewState } from "../../state/types";
import type { CounterResponse } from "../../api/types/execution";
import { change } from "../executionState";
import { counterColumns } from "./columns";
import { selectControl, checkboxControl, buttonControl } from "../../components/controls/factories";

export function CounterPanel({ result, state }: { result: CounterResponse; state: ViewState }) {
  const expression = useRef(state.expression);
  useLayoutEffect(() => {
    expression.current = state.expression;
  }, [state.expression]);
  const metrics = state.meta.metrics;
  const options = useMemo(
    () =>
      metrics.map((metric): Option => [metric.id, `${metric.name ?? ""} [${metric.unit ?? ""}]`]),
    [metrics],
  );
  const rows = useMemo(
    () =>
      result.series.flatMap((series) =>
        series.points.map(([time, value]) => ({
          location: series.location,
          time,
          value,
          metric: result.metric.name,
          unit: result.unit || result.metric.unit,
        })),
      ),
    [result],
  );
  useExport(rows, "counter-data");
  return (
    <>
      <Card
        title="Counter data timeline"
        caption={
          <span>{`${state.counterDerived ? "Derived values use previous-sample alignment between metric streams." : "Min/max envelope preserves extrema at the display resolution."} ${result.metric.description || ""}`}</span>
        }
      >
        <ControlBar
          controls={[
            selectControl(
              "counter-x",
              "X ",
              metrics.find((metric) => metric.id === state.metric)?.id ?? metrics[0]?.id ?? "",
              options,
              (value) => change({ metric: value }),
              {
                ariaLabel: "Primary metric",
              },
            ),
            selectControl(
              "counter-mode",
              "Mode ",
              state.counterMode,
              [
                ["value", "Recorded value"],
                ["delta", "Sample delta"],
                ["rate", "Rate per second"],
              ],
              (value) => change({ counterMode: value }),
            ),
            checkboxControl(
              "derived-toggle",
              "Derived metric",
              state.counterDerived,
              (checked) => change({ counterDerived: checked }),
              {
                labelAfter: true,
                labelClassName: "check",
              },
            ),
          ]}
        />
        {state.counterDerived ? (
          <ControlBar
            controls={[
              selectControl(
                "counter-y",
                "Y ",
                metrics.find((metric) => metric.id === state.metricY)?.id ?? metrics[0]?.id ?? "",
                options,
                (value) => change({ metricY: value }),
                {
                  ariaLabel: "Secondary metric",
                },
              ),
              {
                kind: "text",
                id: "counter-expression",
                ariaLabel: "Derived metric expression",
                label: "Expression ",
                value: state.expression,
                event: "input",
                onChange: (value) => {
                  expression.current = value;
                },
              },
              buttonControl("apply-expression", "Apply", () =>
                change({ expression: expression.current }),
              ),
              {
                kind: "content",
                children: (
                  <span className="muted">{`x, y, + − * / · abs, min, max, sqrt, log`}</span>
                ),
              },
            ]}
          />
        ) : null}
        <div className="chart-wrap">
          <Chart
            id="counter-chart"
            aria-label="Metric timeline"
            spec={{ type: "lines", data: result }}
          />
        </div>
        <div className="filter-line">
          {result.series.map((series, index) => (
            <span key={index} className="legend-item">
              <i className="swatch" style={{ background: palette[index % palette.length] }} />
              {`${locName(series.location)}`}
            </span>
          ))}
        </div>
      </Card>
      <Card title="Metric streams">
        <DataTable
          id="counter-table"
          rows={result.series}
          columns={counterColumns}
          onRow={(row) => inspectObject("Metric recorder", row)}
        />
      </Card>
    </>
  );
}
