import { useCallback, useMemo } from "react";
import type { TransferMatrixResponse } from "../../../api/types/transfers";
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
import { drawTransferMatrix } from "./drawTransferMatrix";
import {
  matrixColumns,
  matrixEvidence,
  matrixMetricOptions,
  matrixMetrics,
  matrixModel,
  type TransferMatrixRow,
} from "./matrixModel";
import { transferTypeOptions, type TransferWidgetProps } from "./transferConfig";
import { TransferDiagnostics } from "./TransferDiagnostics";

export function TransferMatrix({ data, error }: TransferWidgetProps<TransferMatrixResponse>) {
  const settings = useStore((state) => ({
    metric: state.transferMatrixMetric,
    maxGroups: state.transferMatrixMaxGroups,
    types: state.transferMatrixTypes,
  }));
  const metric = matrixMetrics.find(([id]) => id === settings.metric) || matrixMetrics[5];
  const maxGroups = [16, 32, 48].includes(Number(settings.maxGroups))
    ? Number(settings.maxGroups)
    : 32;
  const model = useMemo(() => matrixModel(data, metric), [data, metric]);
  const columns = useMemo(() => matrixColumns(model), [model]);
  const inspectCell = useCallback(
    (row: TransferMatrixRow) => {
      if (data)
        inspectObject("Transfer matrix · cell statistics", matrixEvidence(data, model, row));
    },
    [data, model],
  );
  const chart = useMemo(() => ({ model, error, inspectCell }), [model, error, inspectCell]);
  const draw = useCallback(
    (element: HTMLCanvasElement) => drawTransferMatrix(element, chart),
    [chart],
  );

  return (
    <Card
      title="Transfer matrix"
      caption={
        <span>
          Transfer starts include both window boundaries. Full durations can extend beyond the
          window. Groups combine scalar sums and counts before calculating means or aggregate rate;
          overlapping explicit groups can repeat transfers. Pair ranges describe original location
          pairs before grouping. Function and raw-record status filters do not apply.
        </span>
      }
    >
      <ControlBar
        controls={[
          {
            kind: "select",
            id: "transfer-matrix-metric",
            label: "Metric",
            value: metric[0],
            options: matrixMetricOptions,
            onChange: (value) => {
              updateState({ transferMatrixMetric: value });
              scheduleRender();
            },
          },
          {
            kind: "select",
            id: "transfer-matrix-groups",
            label: "Maximum groups per axis",
            value: maxGroups,
            options: [
              [16, "16"],
              [32, "32"],
              [48, "48"],
            ],
            onChange: (value) => {
              updateState({ transferMatrixMaxGroups: Number(value) });
              scheduleRender();
            },
          },
          {
            kind: "select",
            id: "transfer-matrix-types",
            label: "Transfers",
            value: settings.types || "",
            options: transferTypeOptions,
            onChange: (value) => {
              updateState({ transferMatrixTypes: value });
              scheduleRender();
            },
          },
          {
            kind: "button",
            id: "transfer-matrix-ranges",
            disabled: !data,
            children: "Pair ranges",
            onClick: () => {
              if (data)
                inspectObject("Transfer matrix · original location-pair ranges", {
                  locationPairs: data.locationPairs,
                  ranges: data.locationSummary,
                  grouping: data.grouping,
                  semantics: data.semantics,
                });
            },
          },
          {
            kind: "button",
            id: "transfer-matrix-export",
            disabled: !data,
            children: "Export transfer matrix",
            onClick: () =>
              download(
                "transfer-matrix.json",
                JSON.stringify(
                  {
                    trace: getState().meta?.path,
                    selectedMetric: metric[0],
                    transferTypes: getState().transferMatrixTypes || "",
                    ...data,
                  },
                  null,
                  2,
                ),
              ),
          },
        ]}
      />
      {error ? (
        <p className="analysis-warning" role="alert">
          {error}
        </p>
      ) : (
        <p className="muted">{`${num(data?.totals.count || 0, 0)} transfers across ${num(data?.locationPairs || 0, 0)} recorded location pairs. ${num(model.senders.length, 0)} sender groups × ${num(model.receivers.length, 0)} receiver groups. Select a cell for its members and exact statistics.`}</p>
      )}
      <TransferDiagnostics notes={data?.diagnostics} />
      <div className="chart-wrap">
        <Chart
          id="transfer-matrix-chart"
          aria-label="Transfer matrix, senders in rows and receivers in columns"
          draw={draw}
        />
      </div>
      <DataTable
        id="transfer-matrix-table"
        rows={model.rows}
        columns={columns}
        onRow={inspectCell}
      />
    </Card>
  );
}
