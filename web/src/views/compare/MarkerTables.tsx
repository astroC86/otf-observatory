import { useMemo } from "react";
import { DataTable } from "../../components/table/DataTable";
import { col, timeCol } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import { projectProfiles } from "./profiles";
import type { MarkerResult, TimeRange } from "./types";

type WindowRow = TimeRange & { name: string; offset: number };
const windowColumns: ColumnDef<WindowRow>[] = [
  col("name", "Run"),
  timeCol("offset", "Display offset"),
  timeCol("start", "Recorded start"),
  timeCol("end", "Recorded end"),
];

export function MarkerTables({ result }: { result: MarkerResult }) {
  const windows = useMemo(
    () =>
      result.runs.map((run, index) => ({
        name: index ? `Run ${index}` : "Baseline",
        offset: run.offset,
        ...run.range,
      })),
    [result],
  );
  const profiles = useMemo(() => projectProfiles(result, false), [result]);
  return (
    <>
      <DataTable id="marker-windows" rows={windows} columns={windowColumns} />
      <DataTable id="marker-profiles" {...profiles} />
      <p className="muted card-description">{`${result.durationSemantics} Subpixel timeline intervals coalesce; profiles use the indexed intervals.`}</p>
    </>
  );
}
