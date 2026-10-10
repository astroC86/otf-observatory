import { duration } from "../../lib/format/time";
import type { ViewState } from "../../state/types";
import { inspectAnalysisEvidence } from "../dependencies/inspect";
import { EvidenceTable } from "./EvidenceTable";
import { inspectMatchedProbe, inspectRmaLock } from "./inspect";
import {
  summaryColumns,
  waitColumns,
  mpiCollectiveColumns,
  synchronizationCollectiveColumns,
  requestColumns,
  probeColumns,
  lockColumns,
} from "./columns";
import { EMPTY } from "./types";
import type { WaitResponse, WaitRow } from "./types";

export function WaitEvidenceTables({
  data,
  visible,
  mpi,
  snapshot,
}: {
  data: WaitResponse;
  visible: WaitRow[];
  mpi: boolean;
  snapshot: ViewState;
}) {
  const rows = data.rows || EMPTY,
    collectives = data.collectives || EMPTY,
    requests = data.requests || EMPTY;
  const probes = data.matchedProbes || EMPTY,
    locks = data.rmaLocks || EMPTY;
  const tables = [
    {
      title: "Wait categories",
      id: "wait-summary",
      rows: data.summary || EMPTY,
      columns: summaryColumns,
    },
    {
      title: "Call evidence",
      id: "wait-table",
      rows: visible,
      columns: waitColumns,
      page: {
        field: "waitOffset" as const,
        offset: snapshot.waitOffset,
        total: data.total ?? rows.length,
        more: data.more,
        count: rows.length,
      },
    },
    {
      title: "Collective participation",
      id: "collective-waits",
      rows: collectives,
      columns: mpi ? mpiCollectiveColumns : synchronizationCollectiveColumns,
      maxHeight: 340,
      page: {
        field: "waitCollectiveOffset" as const,
        offset: snapshot.waitCollectiveOffset,
        total: data.collectiveTotal ?? data.totals?.collectiveCount ?? collectives.length,
        more: data.collectivesMore,
      },
      caption: mpi
        ? "Participant overlap is the interval shared by all participants, expressed as a percentage of overall duration. Nonblocking records show request-lifetime overlap. This is not blocked time. Missing participants, invalid intervals or uncertain sequence associations suppress overlap."
        : "Skew measures differing participant arrival times. Missing participants and uncertain sequence associations are reported explicitly.",
    },
    {
      title: "Asynchronous request lifetimes",
      id: "request-table",
      rows: requests,
      columns: requestColumns,
      maxHeight: 340,
      page: {
        field: "waitRequestOffset" as const,
        offset: snapshot.waitRequestOffset,
        total: data.requestTotal ?? data.totals?.requestCount ?? requests.length,
        more: data.requestsMore,
      },
      caption:
        "Request IDs retain their recorded process scope and generation. Completion and test evidence is linked when recorded.",
    },
  ];
  return (
    <>
      {tables.map((table) => (
        <EvidenceTable key={table.id} {...table} onRow={inspectAnalysisEvidence} />
      ))}
      {(probes.length > 0 || Boolean(data.matchedProbeTotal)) && (
        <EvidenceTable
          title="Matched-probe receive lifetimes"
          id="matched-probe-table"
          rows={probes}
          columns={probeColumns}
          onRow={inspectMatchedProbe}
          maxHeight={340}
          page={{
            field: "waitProbeOffset",
            offset: snapshot.waitProbeOffset,
            total: data.matchedProbeTotal || 0,
            more: data.matchedProbesMore,
          }}
          caption="Probe, receive and completion records retain their handle and request generations. Sender candidates and unverified handle scope remain separate from proven message matches."
        />
      )}
      {(locks.length > 0 || Boolean(data.rmaLockTotal)) && (
        <EvidenceTable
          title="RMA lock requests and owners"
          id="rma-lock-table"
          rows={locks}
          columns={lockColumns}
          onRow={inspectRmaLock}
          maxHeight={340}
          page={{
            field: "waitRmaLockOffset",
            offset: snapshot.waitRmaLockOffset,
            total: data.rmaLockTotal || 0,
            more: data.rmaLocksMore,
          }}
          before={
            <p className="filter-line">{`Unavailable time in this selection: ${duration(data.rmaLockCausalTotals?.required)} (union per requesting location).`}</p>
          }
          caption="Request-to-grant latency can include a nonblocking request. Incompatible recorded ownership identifies lock unavailability; it does not measure CPU blocked time."
        />
      )}
    </>
  );
}
