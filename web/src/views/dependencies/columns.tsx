import { bytesCol, col, countCol, timeCol } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import { num } from "../../lib/format/numbers";
import { locName } from "../../state/selectors";
import type { GpuDevice } from "../gpu/types";
import type { RelationshipRecord } from "./types";

const confidenceColumn = col<RelationshipRecord>("confidence", "Evidence", (row) => (
  <span className="evidence-badge">{row.confidence || "unspecified"}</span>
));
export const intervalColumns: ColumnDef<RelationshipRecord>[] = [
  col("kind", "Activity"),
  col("label", "Identity"),
  col("location", "Location", (row) => locName(row.location)),
  timeCol("start", "Start"),
  timeCol("end", "End"),
  col("status", "State"),
  confidenceColumn,
];
export const edgeColumns: ColumnDef<RelationshipRecord>[] = [
  col("kind", "Dependency"),
  col("label", "Description"),
  col("source", "Source"),
  col("target", "Target"),
  confidenceColumn,
  col("evidence", "Source event IDs", (row) => JSON.stringify(row.evidence)),
];
export const candidateColumns: ColumnDef<RelationshipRecord>[] = [
  col("identifier", "Identifier"),
  col("value", "Value"),
  col("host", "Host operation"),
  col("device", "Device operation"),
  col("reason", "Unresolved because"),
];
export const deviceColumns: ColumnDef<GpuDevice>[] = [
  col("name", "Device"),
  col("id", "Identity"),
  timeCol("busy", "Busy union"),
  timeCol("idle", "Idle"),
  timeCol("kernel", "Kernel union"),
  timeCol("copy", "Copy union"),
  timeCol("kernelCopyOverlap", "Kernel/copy overlap"),
  timeCol("overlap", "Concurrent streams"),
  countCol("copies", "Copies"),
  bytesCol("bytes", "Transferred", false),
  confidenceColumn,
  col("utilization", "Recorded activity", (row) =>
    row.utilization == null ? "—" : num(row.utilization * 100, 2) + "%",
  ),
];
