import { useMemo } from "react";
import { EvidenceTable } from "./EvidenceTable";
import { inspectTaskWait } from "./inspect";
import { taskColumns } from "./taskColumns";
import type { TaskAnalysis, TaskWaitRecord } from "./taskTypes";

export function TaskWaits({
  intervals,
  analysis,
}: {
  intervals: readonly TaskWaitRecord[];
  analysis?: TaskAnalysis;
}) {
  const rows = useMemo(
    () => intervals.filter((row) => row.kind === "task-wait" || row.kind === "task-group"),
    [intervals],
  );
  if (!analysis && !rows.length) return null;
  return (
    <EvidenceTable
      title="Tasks associated with waits and taskgroups"
      id="task-waits-table"
      rows={rows}
      columns={taskColumns}
      onRow={inspectTaskWait}
      maxHeight={320}
      caption="Task lists follow the recorded parent context. Taskgroup intervals include useful body execution; their terminal wait entry is unrecorded. Required members form a proved subset. Candidate links do not establish application data flow or blocked duration."
      before={
        analysis?.dataflowReason && (
          <p className="filter-line">
            {analysis.dataflow === "unresolved"
              ? "Task data flow is unresolved. The recorded task lifetimes and possible wait dependencies remain inspectable."
              : analysis.dataflowReason}
          </p>
        )
      }
    />
  );
}
