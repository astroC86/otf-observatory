import type { TransferGroup, TransferTimelineResponse } from "../../../api/types/transfers";
import { bytesCol, countCol, timeCol } from "../../../components/table/columns";
import type { ColumnDef } from "../../../components/table/types";
import { palette } from "../../../lib/color/palette";
import { bytes } from "../../../lib/format/bytes";
import { num } from "../../../lib/format/numbers";
import { duration } from "../../../lib/format/time";
import { transferLabel, transferRate } from "./transferConfig";

export const timelineMetrics = [
  ["count", "Transfer count"],
  ["bytes.sum", "Total bytes"],
  ["duration.sum", "Total duration"],
  ["rate", "Bytes / total duration"],
] as const;

export type TimelineMetric = (typeof timelineMetrics)[number][0];

export interface TransferTimelineRow {
  readonly index: number;
  readonly bin: number;
  readonly start: number;
  readonly end: number;
  readonly count: number;
  readonly bytes: number;
  readonly duration: number;
  readonly rate: number;
}

export const timelineColumns: readonly ColumnDef<TransferTimelineRow>[] = [
  { key: "bin", label: "Bin", number: true },
  timeCol<TransferTimelineRow>("start", "Start"),
  timeCol<TransferTimelineRow>("end", "End"),
  countCol<TransferTimelineRow>("count", "Transfers"),
  bytesCol<TransferTimelineRow>("bytes", "Total bytes"),
  timeCol<TransferTimelineRow>("duration", "Total duration"),
  {
    key: "rate",
    label: "Bytes / total duration",
    number: true,
    render: (_, row) => transferRate(row.rate),
  },
];

export interface TransferTimelineModel {
  readonly group: TransferGroup;
  readonly format: (value: number) => string;
  readonly series: TransferTimelineResponse["displayGroups"][TransferGroup];
  readonly bounds: readonly number[];
  readonly reduction: TransferTimelineResponse["keyReduction"][TransferGroup] | undefined;
  readonly keys: readonly string[];
  readonly labels: ReadonlyMap<string, string>;
  readonly colors: ReadonlyMap<string, string>;
  readonly rows: readonly TransferTimelineRow[];
  readonly maximum: number;
  readonly hasTransfers: boolean;
}

export function timelineModel(
  data: TransferTimelineResponse | null,
  group: TransferGroup,
  metric: TimelineMetric,
): TransferTimelineModel {
  const format =
    metric === "bytes.sum"
      ? bytes
      : metric === "duration.sum"
        ? duration
        : metric === "rate"
          ? transferRate
          : (value: number) => num(value, 0);
  const series = data?.displayGroups?.[group] || [];
  const bounds = data?.binBounds || [];
  const labels = new Map<string, string>();
  for (const bin of series) {
    for (const row of bin) {
      labels.set(
        String(row.key),
        row.other ? "Other" : transferLabel(row.key, group, data?.callsites),
      );
    }
  }
  const keys = [...labels.keys()].toSorted((a, b) => Number(a) - Number(b));
  const colors = new Map(keys.map((key, index) => [key, palette[index % palette.length]!]));
  const resolution = Number(data?.clockResolution);
  const rows = (data?.binTotals || []).map((row, index) => ({
    index,
    bin: index + 1,
    start: bounds[index]!,
    end: bounds[index + 1]!,
    count: row.count,
    bytes: "bytes" in row ? row.bytes.sum || 0 : 0,
    duration: "duration" in row ? row.duration.sum || 0 : 0,
    rate: row.count && "bytes" in row ? row.bytes.sum / (row.duration.sum || 1 / resolution) : 0,
  }));
  const totals = series.map((bin) =>
    bin.reduce((sum, row) => sum + (Number.isFinite(row.value) ? Math.max(0, row.value) : 0), 0),
  );
  return {
    group,
    format,
    series,
    bounds,
    keys,
    labels,
    colors,
    rows,
    reduction: data?.keyReduction?.[group],
    maximum: Math.max(1e-30, ...totals),
    hasTransfers: rows.some((row) => row.count),
  };
}

export function timelineEvidence(
  data: TransferTimelineResponse,
  model: TransferTimelineModel,
  row: TransferTimelineRow,
) {
  return {
    ...row,
    displayedGroups: model.series[row.index],
    workerGroups: data.groups[model.group][row.index],
    keyReduction: model.reduction,
    semantics: data.semantics,
    sourcePositions: model.group === "callsite" ? data.callsites : undefined,
  };
}
