import { num } from "../../lib/format/numbers";
import { countCol, nameCol, timeCol } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import type { FunctionSummaryRow } from "../../api/types/execution";

export type GroupedFunctionRow = Pick<
  FunctionSummaryRow,
  | "id"
  | "name"
  | "group"
  | "calls"
  | "overlapping"
  | "inclusive"
  | "exclusive"
  | "minimum"
  | "maximum"
  | "estimated"
  | "average"
>;
export type FunctionProfileRow = (FunctionSummaryRow | GroupedFunctionRow) & {
  share: number;
};
export const functionColumns: readonly ColumnDef<FunctionProfileRow>[] = [
  nameCol<FunctionProfileRow>(),
  { key: "group", label: "Group" },
  countCol<FunctionProfileRow>("calls", "Calls"),
  countCol<FunctionProfileRow>("overlapping", "Overlapping"),
  timeCol<FunctionProfileRow>("exclusive", "Exclusive"),
  {
    key: "share",
    label: "Share",
    render: (_value, row) => (
      <div className="bar-cell">
        <div className="bar-track">
          <span style={{ width: `${row.share}%` }} />
        </div>
        <span className="mono">{`${num(row.share, 1)}%`}</span>
      </div>
    ),
  },
  timeCol<FunctionProfileRow>("inclusive", "Inclusive"),
  timeCol<FunctionProfileRow>("average", "Mean interval"),
  timeCol<FunctionProfileRow>("minimum", "Min"),
  timeCol<FunctionProfileRow>("maximum", "Max"),
  countCol<FunctionProfileRow>("estimated", "Estimated segments"),
];
