import { countCol, timeCol } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import { num } from "../../lib/format/numbers";
import { locName } from "../../state/selectors";
import type { MetricPixel, MetricSeries } from "./types";

function numberCol<Row extends object>(key: keyof Row & string, label: string): ColumnDef<Row> {
  return { key, label, number: true, render: (value) => num(value, 6) };
}
export const SERIES_COLUMNS: ColumnDef<MetricSeries>[] = [
  { key: "name", label: "Stream", render: (_, row) => row.name || locName(row.location) },
  numberCol("min", "Minimum"),
  numberCol("max", "Maximum"),
  countCol("samples", "Input samples"),
  {
    key: "summary",
    label: "Time reduction",
    render: (_, row) => (row.summary?.operation === "none" ? "—" : num(row.summary?.value, 6)),
  },
  countCol("validSamples", "Valid samples"),
  countCol("missingSamples", "Missing samples"),
];
export const PIXEL_COLUMNS: ColumnDef<MetricPixel>[] = [
  timeCol("start", "Start"),
  timeCol("end", "End"),
  numberCol("mean", "mean"),
  numberCol("min", "min"),
  numberCol("max", "max"),
  numberCol("sum", "sum"),
  countCol("contributors", "Sources"),
  countCol("rawSamples", "Raw samples"),
  { key: "attribution58", label: "attribution58", render: (value) => JSON.stringify(value) },
  { key: "attribution70", label: "attribution70", render: (value) => JSON.stringify(value) },
];
