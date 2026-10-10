import { locName } from "../../state/selectors";
import { num } from "../../lib/format/numbers";
import { countCol } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import type { CounterSeries } from "../../api/types/execution";

export const counterColumns: readonly ColumnDef<CounterSeries>[] = [
  {
    key: "location",
    label: "Recorder",
    render: (_value, row) => locName(row.location),
  },
  {
    key: "min",
    label: "Minimum",
    number: true,
    render: (_value, row) => num(row.min, 6),
  },
  {
    key: "max",
    label: "Maximum",
    number: true,
    render: (_value, row) => num(row.max, 6),
  },
  countCol<CounterSeries>("samples", "Samples"),
];
