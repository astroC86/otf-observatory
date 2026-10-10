import { locName } from "../../state/selectors";
import { num } from "../../lib/format/numbers";
import { countCol, timeCol } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import type { ProcessSummaryRow } from "../../api/types/execution";

export const processColumns: readonly ColumnDef<ProcessSummaryRow>[] = [
  { key: "id", label: "Location", render: (_value, row) => locName(row.id) },
  { key: "type", label: "Type" },
  timeCol<ProcessSummaryRow>("exclusive", "Exclusive time"),
  {
    key: "utilization",
    label: "Recorded activity / interval",
    number: true,
    render: (_value, row) => `${num(row.utilization * 100, 2)}%`,
  },
  countCol<ProcessSummaryRow>("events", "Total archive events"),
];
