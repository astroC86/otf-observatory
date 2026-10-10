import { DataTable } from "../../components/table/DataTable";
import { buttonControl } from "../../components/controls/factories";
import { inspectObject } from "../../state/inspection";
import { locName } from "../../state/selectors";
import { duration } from "../../lib/format/time";
import { download } from "../../lib/download";
import { EvidenceDetail, type DetailSpec } from "./EvidenceDetail";
import { rangeAction } from "./detailActions";
import { CauseDetail } from "./causes/CauseDetail";
import { memberColumns } from "./taskColumns";
import { ownerColumns, senderColumns, rmaTarget } from "./columns";
import { EMPTY } from "./types";
import { taskIdentity, type TaskCandidate, type TaskWaitRecord } from "./taskTypes";
import type { MatchedProbe, RmaLock, WaitCause } from "./types";

let inspection = 0;
function detail(title: string, object: unknown, spec: DetailSpec) {
  inspectObject(title, object, { before: <EvidenceDetail key={++inspection} {...spec} /> });
}
export function inspectWaitCause(cause: WaitCause) {
  inspectObject("Dependency cause", cause, {
    before: <CauseDetail key={++inspection} cause={cause} />,
  });
}
export function inspectTaskWait(wait: TaskWaitRecord) {
  const data = wait.data,
    group = wait.kind === "task-group";
  const tasks = group
    ? (data?.memberTasks || EMPTY).map((task) => ({ ...task, taskGroup: true }))
    : data?.awaitedTasks || data?.candidateTasks || EMPTY;
  detail(`Tasks associated with ${wait.label || "task wait"}`, wait, {
    heading: group
      ? "Recorded taskgroup members"
      : data?.awaitedTasks
        ? "Recorded awaited tasks"
        : data?.recordingContract?.completionOnly
          ? "Dependency completion observation"
          : "Outstanding child candidates",
    body: [
      data?.interpretation || "",
      `${group ? "Whole taskgroup construct" : data?.recordingContract?.completionOnly ? "Observed region" : "Wait"}: ${locName(wait.location)} · ${duration(wait.start)} → ${duration(wait.end)}`,
    ],
    children: (
      <DataTable
        id="task-wait-members"
        rows={tasks}
        columns={memberColumns}
        onRow={inspectTaskWaitCandidate}
        maxHeight={350}
      />
    ),
  });
}
export function inspectTaskWaitCandidate(task: TaskCandidate) {
  const source = task.source,
    target = task.target;
  const meaning = task.taskGroup
    ? task.required
      ? "Recorded execution must complete before this taskgroup returns. The full task set, detached fulfillment and terminal wait duration remain unrecorded."
      : "This recorded member has no proved completion prerequisite; inspect the evidence below."
    : "This remains a candidate; the awaited set is not explicitly recorded.";
  detail("Task instance evidence", task, {
    heading: `Task ${taskIdentity(task.task)}`,
    body: [
      task.status || "Conditional taskwait candidate",
      `Created: ${duration(task.createTime ?? source?.start)}${task.createLocation == null ? "" : ` · ${locName(task.createLocation)}`}`,
      `Completed: ${duration(task.completionTime ?? source?.end)}${task.completionLocation == null ? "" : ` · ${locName(task.completionLocation)}`}`,
      `${task.taskGroup ? "Taskgroup construct" : "Possible dependent wait"}: ${locName(target?.location)} · ${duration(target?.start)} → ${duration(target?.end)}`,
      `Parent evidence: ${task.parentConfidence || "See recorded task identity and event links below"}. ${meaning}`,
    ],
    actions: [
      rangeAction("task-show-lifetime", "Show task lifetime", source),
      rangeAction(
        "task-show-wait",
        `Show ${task.taskGroup ? "taskgroup construct" : "possible dependent wait"}`,
        target,
      ),
    ],
  });
}
export function inspectRmaLock(row: RmaLock) {
  const request = row.request,
    grant = row.grant;
  detail("RMA lock evidence", row, {
    heading: `Window ${row.window ?? ""} · lock ${row.lock ?? ""}`,
    body: [
      row.status || "",
      `Requested: ${request ? `${duration(request.time)} · ${locName(request.location)}` : "Not recorded"}`,
      `Granted: ${grant ? `${duration(grant.time)} · ${locName(grant.location)}` : "Not recorded"}`,
      `Target: ${rmaTarget(row)}`,
      row.unresolvedReasons?.length ? (
        <p className="analysis-warning">{row.unresolvedReasons.join(" · ")}</p>
      ) : null,
      `Recorded unavailable time: ${duration(row.unavailableSeconds)}. Exact blocked time is unknown.`,
    ],
    actions: [
      rangeAction(
        "rma-lock-show",
        "Show request lifetime",
        { start: request?.time, end: grant?.time },
        false,
      ),
      buttonControl("rma-lock-export", "Export lock evidence", () =>
        download("rma-lock-evidence.json", JSON.stringify(row, null, 2), "application/json"),
      ),
    ],
    children: (
      <>
        <h3>Owners preventing the grant</h3>
        <DataTable
          id="rma-lock-causes"
          rows={row.causes || EMPTY}
          columns={ownerColumns}
          onRow={(cause) => inspectWaitCause({ ...cause, analysis: "waits" })}
          maxHeight={320}
        />
      </>
    ),
  });
}
export function inspectMatchedProbe(row: MatchedProbe) {
  detail("Matched-probe lifecycle", row, {
    heading: `Message handle ${row.messageId ?? "Unknown"} · generation ${row.generation ?? "Unknown"}`,
    body: [
      row.status || "",
      row.scopeAssumption || "",
      row.unresolvedReasons?.length ? (
        <ul>
          {row.unresolvedReasons.map((reason, index) => (
            <li key={index}>{reason}</li>
          ))}
        </ul>
      ) : null,
    ],
    actions: (["probe", "receive", "completion"] as const).map((key) =>
      rangeAction(`matched-probe-${key}`, `Show ${key}`, row[key], false),
    ),
    children: (
      <>
        <h3>Sender candidates</h3>
        <p>{`${row.sendCandidates?.length || 0} of ${row.candidateCount || 0}${row.candidateCountComplete === false ? " or more" : ""} candidates displayed`}</p>
        <DataTable
          id="matched-probe-candidates"
          rows={row.sendCandidates || EMPTY}
          columns={senderColumns}
          onRow={(candidate) => inspectObject("Matched-probe sender candidate", candidate)}
          maxHeight={280}
        />
      </>
    ),
  });
}
