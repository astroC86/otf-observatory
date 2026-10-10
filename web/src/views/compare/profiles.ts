import { col, timeCol } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import type { MarkerResult, ProfilesResult, ProfileRow } from "./types";

const EMPTY: ProfileRow[] = [];
export function projectProfiles(
  data: MarkerResult | ProfilesResult | null,
  separateBaseline: boolean,
) {
  const prefix = separateBaseline ? "run" : "time";
  const rows =
    data?.rows.map((row) => {
      const flat: ProfileRow =
        separateBaseline && "baseline" in row
          ? { name: row.name, baseline: row.baseline, baselineCalls: row.baselineCalls }
          : { name: row.name };
      data.runs.forEach((run, index) => {
        const value = row.values[run.id]!;
        flat[`${prefix}${index}`] = value.time;
        flat[`delta${index}`] = value.delta;
        if (separateBaseline) flat[`calls${index}`] = value.calls;
      });
      return flat;
    }) || EMPTY;
  const columns: ColumnDef<ProfileRow>[] = [col("name", "Function")];
  if (separateBaseline) columns.push(timeCol("baseline", "Baseline exclusive"));
  data?.runs.forEach((run, index) => {
    const number = index + Number(separateBaseline);
    columns.push(
      timeCol(`${prefix}${index}`, number ? `Run ${number} exclusive` : "Baseline exclusive"),
    );
    if (number) columns.push(timeCol(`delta${index}`, `Δ Run ${number}`));
  });
  return { rows, columns };
}
