import { col, timeCol } from "../../../components/table/columns";
import type { ColumnDef } from "../../../components/table/types";
import { duration } from "../../../lib/format/time";
import { locName } from "../../../state/selectors";
import type { WaitCause, WaitRow } from "../types";
import { operationName } from "./prepare";
import type { ActivitySegment, UpstreamAlternative, UpstreamNode } from "./types";

export const causeColumns: ColumnDef<WaitCause>[] = [
  col("source", "Enabling operation", (r) => operationName(r.source)),
  col("source", "Source rank / thread", (r) => locName(r.source?.location)),
  col("target", "Affected operation", (r) => operationName(r.target)),
  col("target", "Waiting rank / thread", (r) => locName(r.target?.location)),
  col("dependency", "Dependency delay", (r) => duration(r.dependency?.duration)),
  timeCol("readinessTime", "Prerequisite arrival", false),
  col("limiting", "Limits this estimate", (r) => (r.limiting ? "Yes" : "—")),
  col("confidence", "Evidence"),
  col("relation", "Relationship"),
];
export const unresolvedColumns: ColumnDef<WaitRow>[] = [
  col("routine", "Call"),
  col("location", "Rank / thread", (r) => locName(r.location)),
  col(
    "unresolvedReason",
    "Reason",
    (r) =>
      r.unresolvedReason ||
      r.evidence?.interpretation ||
      "No enabling operation identified in the recorded evidence.",
  ),
];
export const treeColumns: ColumnDef<UpstreamNode>[] = [
  col("id", "Link", (r) => `#${r.id + 1}`),
  col("parent", "Precedes", (r) => (r.parent == null ? "Selected wait" : `Link #${r.parent + 1}`)),
  col("cause", "Enabling rank / thread", (r) => locName(r.cause.source?.location)),
  col("cause", "Enabling operation", (r) => operationName(r.cause.source)),
  col("cause", "Affected operation", (r) => operationName(r.cause.target)),
  col("cause", "Overlapping delay", (r) => duration(r.cause.dependency?.duration)),
  col("taskOrder", "Execution order", (r) =>
    r.taskOrder
      ? `Task ${r.taskOrder.task.join(" / ")}${r.taskOrder.predecessorExecution.location !== r.taskOrder.enablingExecution.location ? " · migrated" : ""}`
      : r.parent == null
        ? "Selected cause"
        : "Recorded location",
  ),
];
export const activityColumns: ColumnDef<ActivitySegment>[] = [
  timeCol("start", "From", false),
  timeCol("end", "To", false),
  timeCol("duration", "Time", false),
  col("operations", "Recorded activity", (r) =>
    r.operations?.length
      ? `${r.operations.map(operationName).join(", ")}${r.operationCount > r.operations.length ? ` (+${r.operationCount - r.operations.length})` : ""}`
      : "No attributable region",
  ),
  col("status", "Evidence"),
];
export const alternativeColumns: ColumnDef<UpstreamAlternative>[] = [
  col("cause", "Enabling operation", (r) => operationName(r.cause.source)),
  col("cause", "Affected operation", (r) => operationName(r.cause.target)),
  col("cause", "Overlap", (r) => duration(r.cause.dependency?.duration)),
  col("reason", "Propagation limit"),
];
