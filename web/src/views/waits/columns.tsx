import { col, countCol, timeCol } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import { duration } from "../../lib/format/time";
import { num } from "../../lib/format/numbers";
import { locName } from "../../state/selectors";
import type { WaitRow, MatchedProbe, RmaLock, SenderCandidate, WaitCause } from "./types";

export const summaryColumns: ColumnDef<WaitRow>[] = [
  col("category", "Category"),
  countCol("count", "Calls"),
  timeCol("observed", "Observed time"),
  timeCol("inferred", "Delay estimate"),
  timeCol("lowerBound", "Blocked lower bound"),
  timeCol("upperBound", "Blocked upper bound"),
];
export const waitColumns: ColumnDef<WaitRow>[] = [
  col("category", "Category"),
  col("routine", "Routine"),
  col("location", "Location", (r) => locName(r.location)),
  timeCol("start", "Start"),
  timeCol("observed", "Observed"),
  timeCol("inferred", "Delay estimate"),
  col("peer", "Peer", (r) => (r.peer == null ? "—" : locName(r.peer))),
  col("confidence", "Evidence", (r) => (
    <span className="evidence-badge">{r.confidence || "unspecified"}</span>
  )),
];
const collectivePrefix: ColumnDef<WaitRow>[] = [
  col("operation", "Operation"),
  col("comm", "Communicator"),
  countCol("sequence", "Sequence"),
  timeCol("arrivalSkew", "Arrival skew"),
];
const collectiveSuffix: ColumnDef<WaitRow>[] = [
  col("participants", "Participants", (r) =>
    Array.isArray(r.participants) ? r.participants.length : (r.participants ?? ""),
  ),
  countCol("expectedParticipants", "Expected"),
  col("complete", "Complete", (r) => (r.complete ? "Yes" : "No")),
];
export const synchronizationCollectiveColumns = [...collectivePrefix, ...collectiveSuffix];
export const mpiCollectiveColumns: ColumnDef<WaitRow>[] = [
  ...collectivePrefix,
  timeCol("overallDuration", "Overall duration"),
  col("participantOverlap", "Participant overlap", (r) => duration(r.participantOverlap)),
  col("participantOverlapPercent", "Overlap %", (r) =>
    r.participantOverlapPercent == null ? "—" : `${num(r.participantOverlapPercent, 2)}%`,
  ),
  ...collectiveSuffix,
];
export const requestColumns: ColumnDef<WaitRow>[] = [
  col("location", "Initiating thread", (r) => locName(r.location)),
  col("completionLocation", "Completing thread", (r) =>
    r.completionLocation == null ? "—" : locName(r.completionLocation),
  ),
  col("request", "Request"),
  countCol("generation", "Generation"),
  col("kind", "Kind"),
  timeCol("start", "Posted"),
  timeCol("end", "Completed"),
  col("status", "State"),
];
export const probeColumns: ColumnDef<MatchedProbe>[] = [
  col("messageId", "Message handle"),
  col("generation", "Generation"),
  col("probe", "Probing rank / thread", (r) => (r.probe ? locName(r.probe.location) : "—")),
  col("probe", "Probe", (r) => r.probe?.routine || "—"),
  col("receive", "Receive", (r) => r.receive?.routine || "—"),
  col("completion", "Completion observation", (r) =>
    r.completion ? duration(r.completion.eventTime ?? r.completion.end) : "—",
  ),
  col("request", "Request / generation", (r) =>
    r.request ? `${r.request.id} / ${r.request.generation}` : "—",
  ),
  col("candidateCount", "Sender candidates"),
  col("status", "State"),
];
export function rmaTarget(row: RmaLock): string {
  if (row.allTargets) return "All window targets";
  const value = row.targetIdentity;
  return value == null
    ? "Unresolved"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
}
export const lockColumns: ColumnDef<RmaLock>[] = [
  col("request", "Requesting rank / thread", (r) =>
    r.request ? locName(r.request.location) : "—",
  ),
  col("window", "Window"),
  col("lock", "Lock"),
  col("targetIdentity", "Target", rmaTarget),
  col("request", "Requested", (r) => (r.request ? duration(r.request.time) : "—")),
  col("grant", "Granted", (r) => (r.grant ? duration(r.grant.time) : "—")),
  timeCol("selectedUnavailableSeconds", "Unavailable in selection", false),
  col("causes", "Owners", (r) => num(r.causes?.length || 0, 0)),
  col("status", "State"),
];
export const senderColumns: ColumnDef<SenderCandidate>[] = [
  col("operation", "Sender", (r) => locName(r.operation?.location)),
  col("operation", "Operation", (r) => r.operation?.routine || "Unidentified operation"),
  timeCol("time", "Send recorded", false),
  col("operation", "Event", (r) => r.operation?.event ?? ""),
  col("bytes", "Bytes"),
];
export const ownerColumns: ColumnDef<WaitCause>[] = [
  col("source", "Owner rank / thread", (r) => locName(r.source?.location)),
  col("source", "Enabling operation", (r) => r.source?.routine || "Lock release"),
  timeCol("readinessTime", "Released", false),
  col(
    "dependency",
    "Unavailable interval",
    (r) => `${duration(r.dependency?.start)} → ${duration(r.dependency?.end)}`,
  ),
  col("dependency", "Time", (r) => duration(r.dependency?.duration)),
  col("confidence", "Evidence"),
];
