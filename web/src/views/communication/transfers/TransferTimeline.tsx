import { useCallback, useMemo } from "react";
import type { TransferTimelineResponse } from "../../../api/types/transfers";
import { Chart } from "../../../components/chart/Chart";
import { ControlBar } from "../../../components/controls/ControlBar";
import { Card } from "../../../components/panel/Card";
import { DataTable } from "../../../components/table/DataTable";
import { palette } from "../../../lib/color/palette";
import { download } from "../../../lib/download";
import { num } from "../../../lib/format/numbers";
import { inspectObject } from "../../../state/inspection";
import { getState, updateState } from "../../../state/store";
import { useStore } from "../../../state/useStore";
import { scheduleRender } from "../../../state/viewActions";
import { drawTransferTimeline } from "./drawTransferTimeline";
import {
  timelineColumns,
  timelineEvidence,
  timelineMetrics,
  timelineModel,
  type TransferTimelineRow,
} from "./timelineModel";
import { timelineGroups, transferTypeOptions, type TransferWidgetProps } from "./transferConfig";
import { TransferDiagnostics } from "./TransferDiagnostics";

export function TransferTimeline({ data, error }: TransferWidgetProps<TransferTimelineResponse>) {
  const settings = useStore((state) => ({
    group: state.transferTimelineGroup,
    metric: state.transferTimelineMetric,
    bins: state.transferTimelineBins,
    maxKeys: state.transferTimelineMaxKeys,
    types: state.transferTimelineTypes,
  }));
  const group = timelineGroups.find(([id]) => id === settings.group)?.[0] || "type";
  const metric = timelineMetrics.find(([id]) => id === settings.metric)?.[0] || "count";
  const model = useMemo(() => timelineModel(data, group, metric), [data, group, metric]);
  const inspectBin = useCallback(
    (row: TransferTimelineRow) => {
      if (data)
        inspectObject(`Transfer timeline · bin ${row.bin}`, timelineEvidence(data, model, row));
    },
    [data, model],
  );
  const chart = useMemo(() => ({ model, error, inspectBin }), [model, error, inspectBin]);
  const draw = useCallback(
    (element: HTMLCanvasElement) => drawTransferTimeline(element, chart),
    [chart],
  );
  const { reduction, keys, colors, labels } = model;

  return (
    <Card
      title="Transfer timeline"
      caption={
        <span>
          Each bin includes transfer starts at both boundaries and retains complete transfer
          lifetimes. A start exactly on an internal boundary appears in both bins. Zero-width bins
          are empty. The key limit applies across all bins and preserves cutoff ties. Function
          filters do not apply.
        </span>
      }
    >
      <ControlBar
        controls={[
          {
            kind: "select",
            id: "transfer-timeline-group",
            label: "Group by",
            value: group,
            options: timelineGroups,
            onChange: (value) => {
              updateState({ transferTimelineGroup: value });
              scheduleRender();
            },
          },
          {
            kind: "select",
            id: "transfer-timeline-metric",
            label: "Quantity",
            value: metric,
            options: timelineMetrics,
            onChange: (value) => {
              updateState({ transferTimelineMetric: value });
              scheduleRender();
            },
          },
          {
            kind: "select",
            id: "transfer-timeline-bins",
            label: "Bins",
            value: settings.bins || 100,
            options: [25, 50, 100, 200],
            onChange: (value) => {
              updateState({ transferTimelineBins: Number(value) });
              scheduleRender();
            },
          },
          {
            kind: "select",
            id: "transfer-timeline-maxkeys",
            label: "Key limit",
            value: settings.maxKeys ?? 20,
            options: [8, 20, 32, 100],
            onChange: (value) => {
              updateState({ transferTimelineMaxKeys: Number(value) });
              scheduleRender();
            },
          },
          {
            kind: "select",
            id: "transfer-timeline-types",
            label: "Transfers",
            value: settings.types || "",
            options: transferTypeOptions,
            onChange: (value) => {
              updateState({ transferTimelineTypes: value });
              scheduleRender();
            },
          },
          {
            kind: "button",
            id: "transfer-timeline-export",
            disabled: !data,
            children: "Export timeline",
            onClick: () =>
              download(
                "transfer-timeline.json",
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
        <p className="muted">{`${num(data?.totals.count || 0, 0)} unique transfers · ${num(data?.binRecordCount || 0, 0)} bin contributions · ${num(data?.boundaryDuplicateCount || 0, 0)} repeated boundary contributions.`}</p>
      )}
      {reduction?.triggered ? (
        <p className="muted">{`${num(reduction.retainedKeyCount, 0)} of ${num(reduction.originalKeyCount, 0)} keys retained; other keys are merged per bin. Equal scores remain together.`}</p>
      ) : null}
      {metric === "rate" ? (
        <p className="muted">
          Each group rate is bytes divided by its total transfer duration. Stacked group rates are
          not a whole-bin throughput measurement.
        </p>
      ) : null}
      <TransferDiagnostics notes={data?.diagnostics} />
      <div className="chart-wrap">
        <Chart id="transfer-timeline-chart" aria-label="Transfer summary timeline" draw={draw} />
      </div>
      <div className="filter-line">
        {keys.slice(0, 24).map((key) => (
          <span key={key} className="legend-item">
            <i className="swatch" style={{ background: colors.get(key) || palette[0] }} />
            {labels.get(key)}
          </span>
        ))}
        {keys.length > 24 ? (
          <span className="muted">{`${keys.length - 24} additional groups; click a bin to inspect all groups.`}</span>
        ) : null}
      </div>
      <DataTable
        id="transfer-timeline-table"
        rows={model.rows}
        columns={timelineColumns}
        onRow={inspectBin}
      />
    </Card>
  );
}
