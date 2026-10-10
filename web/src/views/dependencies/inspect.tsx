import { inspectObject } from "../../state/inspection";
import { setRange } from "../../state/rangeActions";
import { inspectTaskWait, inspectTaskWaitCandidate, inspectWaitCause } from "../waits/inspect";
import type { RelationshipRecord } from "./types";

export function inspectAnalysisEvidence(row: RelationshipRecord) {
  // The relationship endpoint carries tagged task/wait evidence in these payloads.
  if (row.waitCause)
    return inspectWaitCause(row.waitCause as Parameters<typeof inspectWaitCause>[0]);
  if (row.kind === "rma-lock-contention")
    return inspectWaitCause({
      ...(row.data as Parameters<typeof inspectWaitCause>[0]),
      analysis: "waits",
    });
  if (row.kind === "task-wait")
    return inspectTaskWait(row as Parameters<typeof inspectTaskWait>[0]);
  if (row.kind === "task-wait-candidate")
    return inspectTaskWaitCandidate(row.data as Parameters<typeof inspectTaskWaitCandidate>[0]);
  const { start, end } = row;
  inspectObject(row.label || row.routine || row.kind || row.category || "Analysis evidence", row, {
    after:
      start != null && end != null && end > start ? (
        <button id="analysis-zoom" className="primary" onClick={() => setRange(start, end)}>
          Zoom to this interval
        </button>
      ) : null,
  });
}
