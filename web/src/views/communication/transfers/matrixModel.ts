import type {
  TransferLocationGroup,
  TransferMatrixCell,
  TransferMatrixResponse,
} from "../../../api/types/transfers";
import { countCol } from "../../../components/table/columns";
import type { ColumnDef } from "../../../components/table/types";
import { bytes } from "../../../lib/format/bytes";
import { num } from "../../../lib/format/numbers";
import { duration } from "../../../lib/format/time";

export const matrixMetrics = [
  ["count", "Transfer count", "count"],
  ["duration.sum", "Total duration", "time"],
  ["duration.minimum", "Minimum duration", "time"],
  ["duration.maximum", "Maximum duration", "time"],
  ["duration.mean", "Mean duration", "time"],
  ["bytes.sum", "Total bytes", "bytes"],
  ["bytes.minimum", "Minimum bytes", "bytes"],
  ["bytes.maximum", "Maximum bytes", "bytes"],
  ["bytes.mean", "Mean bytes", "bytes"],
  ["rate.minimum", "Minimum rate", "rate"],
  ["rate.maximum", "Maximum rate", "rate"],
  ["rate.aggregate", "Total bytes / total duration", "rate"],
] as const;

export const matrixMetricOptions = matrixMetrics.map(([id, label]) => [id, label] as const);
export type MatrixMetric = (typeof matrixMetrics)[number];

export interface TransferMatrixRow extends TransferMatrixCell {
  readonly sourceName: string;
  readonly targetName: string;
  readonly value: number;
}

function matrixValue(row: TransferMatrixCell, key: MatrixMetric[0], resolution: number): number {
  if (row.values && Object.hasOwn(row.values, key)) return row.values[key]!;
  switch (key) {
    case "count":
      return row.count;
    case "rate.minimum":
      return row.rate.minimum;
    case "rate.maximum":
      return row.rate.maximum;
    case "rate.aggregate":
      return row.duration.sum ? row.bytes.sum / row.duration.sum : row.bytes.sum * resolution;
    case "duration.sum":
      return row.duration.sum;
    case "duration.minimum":
      return row.duration.minimum;
    case "duration.maximum":
      return row.duration.maximum;
    case "duration.mean":
      return row.duration.count ? row.duration.sum / row.duration.count : 0;
    case "bytes.sum":
      return row.bytes.sum;
    case "bytes.minimum":
      return row.bytes.minimum;
    case "bytes.maximum":
      return row.bytes.maximum;
    case "bytes.mean":
      return row.bytes.count ? row.bytes.sum / row.bytes.count : 0;
  }
}

export function locationGroupLabel(group: TransferLocationGroup | undefined): string {
  return group?.name || group?.id || "Unknown location group";
}

export interface TransferMatrixModel {
  readonly metric: MatrixMetric;
  readonly format: (value: number) => string;
  readonly senders: readonly TransferLocationGroup[];
  readonly receivers: readonly TransferLocationGroup[];
  readonly senderMap: ReadonlyMap<string, TransferLocationGroup>;
  readonly receiverMap: ReadonlyMap<string, TransferLocationGroup>;
  readonly senderIndexes: ReadonlyMap<string, number>;
  readonly receiverIndexes: ReadonlyMap<string, number>;
  readonly rows: readonly TransferMatrixRow[];
  readonly maximum: number;
  readonly height: number;
}

export function matrixModel(
  data: TransferMatrixResponse | null,
  metric: MatrixMetric,
): TransferMatrixModel {
  const format =
    metric[2] === "time"
      ? duration
      : metric[2] === "bytes"
        ? bytes
        : metric[2] === "rate"
          ? (value: number) => `${bytes(value)}/s`
          : (value: number) => num(value, 0);
  const resolution = Number(data?.clockResolution || 1);
  const senders = data?.senderGroups || [];
  const receivers = data?.receiverGroups || [];
  const senderMap = new Map(senders.map((group) => [group.id, group]));
  const receiverMap = new Map(receivers.map((group) => [group.id, group]));
  const rows = (data?.cells || []).map((row) => ({
    ...row,
    sourceName: locationGroupLabel(senderMap.get(row.source)),
    targetName: locationGroupLabel(receiverMap.get(row.target)),
    value: matrixValue(row, metric[0], resolution),
  }));
  return {
    metric,
    format,
    senders,
    receivers,
    senderMap,
    receiverMap,
    rows,
    senderIndexes: new Map(senders.map((group, index) => [group.id, index])),
    receiverIndexes: new Map(receivers.map((group, index) => [group.id, index])),
    maximum: Math.max(1e-30, ...rows.map((row) => (Number.isFinite(row.value) ? row.value : 0))),
    height: Math.max(160, senders.length * 20 + 102),
  };
}

export function matrixColumns(model: TransferMatrixModel): readonly ColumnDef<TransferMatrixRow>[] {
  return [
    { key: "sourceName", label: "Sender group" },
    { key: "targetName", label: "Receiver group" },
    {
      key: "value",
      label: model.metric[1],
      number: true,
      render: (_, row) => model.format(row.value),
    },
    countCol<TransferMatrixRow>("count", "Transfers"),
  ];
}

export function matrixEvidence(
  data: TransferMatrixResponse,
  model: TransferMatrixModel,
  row: TransferMatrixRow,
) {
  return {
    source: model.senderMap.get(row.source),
    target: model.receiverMap.get(row.target),
    selectedMetric: {
      name: model.metric[0],
      value: row.value,
      formatted: model.format(row.value),
    },
    statistics: row,
    window: { start: data.start, end: data.end },
    clockResolution: data.clockResolution,
    semantics: data.semantics,
    diagnostics: data.diagnostics,
  };
}
