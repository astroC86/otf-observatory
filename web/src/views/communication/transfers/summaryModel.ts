import type {
  TransferGroup,
  TransferGroupRow,
  TransferSummaryResponse,
} from "../../../api/types/transfers";
import { bytesCol, countCol, timeCol } from "../../../components/table/columns";
import type { ColumnDef } from "../../../components/table/types";
import { bytes } from "../../../lib/format/bytes";
import { num } from "../../../lib/format/numbers";
import { duration } from "../../../lib/format/time";
import { transferLabel, transferRate } from "./transferConfig";

export const summaryMetrics = [
  ["count", "Transfer count"],
  ["byteSum", "Total bytes"],
  ["durationSum", "Total duration"],
] as const;

export type SummaryMetric = (typeof summaryMetrics)[number][0];

export interface TransferSummaryRow extends TransferGroupRow {
  readonly label: string;
  readonly byteSum: number;
  readonly byteMin: number;
  readonly byteMax: number;
  readonly byteMean: number | null;
  readonly durationSum: number;
  readonly durationMin: number;
  readonly durationMax: number;
  readonly durationMean: number | null;
  readonly rateMin: number;
  readonly rateMax: number;
}

export function summaryRows(
  data: TransferSummaryResponse | null,
  group: TransferGroup,
): TransferSummaryRow[] {
  return (data?.groups[group] || []).map((row) => ({
    ...row,
    label: transferLabel(row.key, group, data?.callsites),
    byteSum: row.bytes.sum,
    byteMin: row.bytes.minimum,
    byteMax: row.bytes.maximum,
    byteMean: row.bytes.count ? row.bytes.sum / row.bytes.count : null,
    durationSum: row.duration.sum,
    durationMin: row.duration.minimum,
    durationMax: row.duration.maximum,
    durationMean: row.duration.count ? row.duration.sum / row.duration.count : null,
    rateMin: row.rate.minimum,
    rateMax: row.rate.maximum,
  }));
}

export function summaryColumns(groupLabel: string): readonly ColumnDef<TransferSummaryRow>[] {
  return [
    { key: "label", label: groupLabel },
    countCol<TransferSummaryRow>("count", "Transfers"),
    bytesCol<TransferSummaryRow>("byteSum", "Total bytes"),
    bytesCol<TransferSummaryRow>("byteMin", "Min bytes"),
    bytesCol<TransferSummaryRow>("byteMax", "Max bytes"),
    bytesCol<TransferSummaryRow>("byteMean", "Mean bytes"),
    timeCol<TransferSummaryRow>("durationSum", "Total duration"),
    timeCol<TransferSummaryRow>("durationMin", "Min duration"),
    timeCol<TransferSummaryRow>("durationMax", "Max duration"),
    timeCol<TransferSummaryRow>("durationMean", "Mean duration"),
    {
      key: "rateMin",
      label: "Min rate",
      number: true,
      render: (_, row) => transferRate(row.rateMin),
    },
    {
      key: "rateMax",
      label: "Max rate",
      number: true,
      render: (_, row) => transferRate(row.rateMax),
    },
  ];
}

export interface TransferSummaryChartSpec {
  readonly rows: readonly TransferSummaryRow[];
  readonly visible: readonly TransferSummaryRow[];
  readonly metric: SummaryMetric;
  readonly format: (value: number) => string;
  readonly maximum: number;
  readonly height: number;
  readonly error: string | null;
}

export function summaryChart(
  rows: readonly TransferSummaryRow[],
  metric: SummaryMetric,
  error: string | null,
): TransferSummaryChartSpec {
  const visible = rows.toSorted((a, b) => b[metric] - a[metric]).slice(0, 32);
  return {
    rows,
    visible,
    metric,
    format:
      metric === "byteSum" ? bytes : metric === "durationSum" ? duration : (value) => num(value, 0),
    maximum: Math.max(
      1e-30,
      ...visible.map((row) => (Number.isFinite(row[metric]) ? row[metric] : 0)),
    ),
    height: Math.max(100, visible.length * 29 + 40),
    error,
  };
}
