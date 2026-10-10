import { DataTable } from "../../../components/table/DataTable";
import { duration } from "../../../lib/format/time";
import { inspectObject } from "../../../state/inspection";
import { EvidenceTable } from "../EvidenceTable";
import { inspectWaitCause } from "../inspect";
import type { CauseData } from "../types";
import { causeColumns, unresolvedColumns } from "./columns";

export function WaitCauses({ data }: { data: CauseData }) {
  return (
    <EvidenceTable
      title="Dependency causes"
      id="wait-causes-table"
      rows={data.causes}
      columns={causeColumns}
      onRow={inspectWaitCause}
      maxHeight={380}
      page={data.pagination ? { ...data.pagination, field: "waitCauseOffset" } : undefined}
      caption="Click a link to inspect the enabling operation and affected wait. Dependency delay measures time before a prerequisite arrives; it is separate from measured call duration and exact blocked time."
      before={
        <>
          <p className="filter-line">{`${data.causes.length} operation links on this page · ${data.unresolved.length} calls without an identified prerequisite${data.independent ? ` · ${data.independent} calls with no external prerequisite` : ""}`}</p>
          {data.totals && (
            <p className="filter-line">
              <span>
                {"Selection delay union: "}
                <span className="quantity">{duration(data.totals.required)}</span>
                {" from required prerequisites · "}
                <span className="quantity">{duration(data.totals.conditional)}</span>
                {
                  " conditional. Overlapping causes are counted once per waiting location within each category."
                }
              </span>
            </p>
          )}
        </>
      }
    >
      {data.unresolved.length > 0 && (
        <details className="metric-help">
          <summary>Calls without attribution</summary>
          <DataTable
            id="wait-unresolved-table"
            rows={data.unresolved}
            columns={unresolvedColumns}
            onRow={(row) => inspectObject("Unresolved wait attribution", row)}
            maxHeight={260}
          />
        </details>
      )}
    </EvidenceTable>
  );
}
