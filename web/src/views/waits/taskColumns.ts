import type { ColumnDef } from "../../components/table/types";
import { locName } from "../../state/selectors";
import { col, timeCol } from "../../components/table/columns";
import { taskIdentity, type TaskCandidate, type TaskWaitRecord } from "./taskTypes";

const CONSTRUCTS: Record<string, string> = {
  "all-direct-children": "Ordinary taskwait",
  "depend-clause": "Taskwait with dependencies",
  "depend-nowait": "Taskwait with dependencies + nowait",
};
export const taskColumns: ColumnDef<TaskWaitRecord>[] = [
  col("location", "Rank / thread", (r) => locName(r.location)),
  timeCol("start", "Recorded start", false),
  timeCol("end", "Recorded end", false),
  col("data", "Construct", (r) =>
    r.kind === "task-group"
      ? "Taskgroup (body + synchronization)"
      : CONSTRUCTS[r.data?.waitSemantics || ""] || "Unresolved taskwait",
  ),
  col("data", "Waiting task", (r) => r.data?.waitingTaskInstance || "Unresolved"),
  col("data", "Awaited set", (r) =>
    r.data?.awaitedTasks
      ? `${r.data.awaitedTasks.length} recorded tasks`
      : "Not explicitly recorded",
  ),
  col(
    "data",
    "Child candidates",
    (r) =>
      `${r.data?.candidateCount ?? 0}${r.data?.candidateSetTruncated ? ` of ${r.data.candidateTotal}` : ""}`,
  ),
  col("data", "Required recorded members", (r) => r.data?.requiredTaskCount ?? "—"),
];
export const memberColumns: ColumnDef<TaskCandidate>[] = [
  col("task", "Task identity", (r) => taskIdentity(r.task)),
  col("taskInstance", "Instance"),
  col("createEvent", "Creation event"),
  col("createLocation", "Creating rank / thread", (r) =>
    r.createLocation == null ? "—" : locName(r.createLocation),
  ),
  col("completionEvent", "Completion event"),
  col("completionLocation", "Completing rank / thread", (r) =>
    r.completionLocation == null ? "—" : locName(r.completionLocation),
  ),
  timeCol("completionTime", "Completed", false),
  col("status", "State"),
  col("required", "Prerequisite", (r) =>
    r.taskGroup ? (r.required ? "Required recorded execution" : "Unresolved") : "Candidate",
  ),
  col("parentConfidence", "Parent evidence"),
];
