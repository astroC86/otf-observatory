import { useCallback, useMemo } from "react";
import type { TransferSummaryResponse } from "../../../api/types/transfers";
import { Chart } from "../../../components/chart/Chart";
import { ControlBar } from "../../../components/controls/ControlBar";
import { Card } from "../../../components/panel/Card";
import { DataTable } from "../../../components/table/DataTable";
import { download } from "../../../lib/download";
import { num } from "../../../lib/format/numbers";
import { inspectObject } from "../../../state/inspection";
import { getState, updateState } from "../../../state/store";
import { useStore } from "../../../state/useStore";
import { scheduleRender } from "../../../state/viewActions";
import { drawTransferSummary } from "./drawTransferSummary";
import { summaryChart, summaryColumns, summaryMetrics, summaryRows } from "./summaryModel";
import { summaryGroups, transferTypeOptions, type TransferWidgetProps } from "./transferConfig";
import { TransferDiagnostics } from "./TransferDiagnostics";

export function TransferSummary({ data, error }: TransferWidgetProps<TransferSummaryResponse>) {
  const settings = useStore((state) => ({
    group: state.transferSummaryGroup,
    metric: state.transferSummaryMetric,
    types: state.transferSummaryTypes,
  }));
  const [group, groupLabel] =
    summaryGroups.find(([id]) => id === settings.group) || summaryGroups[0];
  const metric = summaryMetrics.find(([id]) => id === settings.metric)?.[0] || "count";
  const rows = useMemo(() => summaryRows(data, group), [data, group]);
  const columns = useMemo(() => summaryColumns(groupLabel), [groupLabel]);
  const chart = useMemo(() => summaryChart(rows, metric, error), [rows, metric, error]);
  const draw = useCallback(
    (element: HTMLCanvasElement) => drawTransferSummary(element, chart),
    [chart],
  );

  return (
    <Card
      title="Transfer summary"
      caption={
        <span>
          Includes transfers starting at either window boundary, grouped by sender location
          selection. Full transfer durations can extend beyond the selected window; overlapping
          lifetimes add independently. Rates are bytes divided by duration, with one recorded clock
          tick for zero-duration transfers. Function and raw-record status filters do not apply.
        </span>
      }
    >
      <ControlBar
        controls={[
          {
            kind: "select",
            id: "transfer-summary-group",
            label: "Group by",
            value: group,
            options: summaryGroups,
            onChange: (value) => {
              updateState({ transferSummaryGroup: value });
              scheduleRender();
            },
          },
          {
            kind: "select",
            id: "transfer-summary-metric",
            label: "Chart",
            value: metric,
            options: summaryMetrics,
            onChange: (value) => {
              updateState({ transferSummaryMetric: value });
              scheduleRender();
            },
          },
          {
            kind: "select",
            id: "transfer-summary-types",
            label: "Transfers",
            value: settings.types || "",
            options: transferTypeOptions,
            onChange: (value) => {
              updateState({ transferSummaryTypes: value });
              scheduleRender();
            },
          },
          {
            kind: "button",
            id: "transfer-summary-export",
            disabled: !data,
            children: "Export transfer summary",
            onClick: () =>
              download(
                "transfer-summary.json",
                JSON.stringify({ trace: getState().meta?.path, ...data }, null, 2),
              ),
          },
        ]}
      />
      {error ? (
        <p className="analysis-warning" role="alert">
          {error}
        </p>
      ) : (
        <p className="muted">{`${num(data?.totals.count, 0)} transfers start in the selected window. Durations include each complete transfer.`}</p>
      )}
      <TransferDiagnostics notes={data?.diagnostics} />
      <div className="chart-wrap">
        <Chart id="transfer-summary-chart" aria-label="Transfer summary histogram" draw={draw} />
      </div>
      <DataTable
        id="transfer-summary-table"
        rows={rows}
        columns={columns}
        onRow={(row) =>
          inspectObject(`Transfer summary · ${row.label}`, {
            ...row,
            sourcePosition: data?.callsites[row.key],
            semantics: data?.semantics,
          })
        }
      />
    </Card>
  );
}
