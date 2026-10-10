import { Fragment } from "react";
import { DataTable } from "../../components/table/DataTable";
import { col, timeCol } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import { download } from "../../lib/download";
import { num } from "../../lib/format/numbers";
import { duration } from "../../lib/format/time";
import { inspectObject } from "../../state/inspection";
import { setRange } from "../../state/rangeActions";
import { locName } from "../../state/selectors";
import type { ExternalMapping, ExternalRecord } from "./types";

const EMPTY_RECORDS: ExternalRecord[] = [];
const SECTIONS = [
  ["external", "External records", 250],
  ["internal", "Internal API and device records", 350],
] as const;
const COLUMNS: ColumnDef<ExternalRecord>[] = [
  col("label", "Operation", (row) => row.label || row.recordType || row.kind || row.id),
  col("location", "Rank / thread / stream", (row) => locName(row.location)),
  col("event", "Evidence event"),
  col("domain", "Identifier namespace", (row) => row.domain || "External identity"),
  timeCol("start", "Recorded start", false),
  timeCol("end", "Recorded end", false),
];

function inspectRecord(row: ExternalRecord) {
  const { start, end } = row;
  const hasRange =
    start != null && end != null && Number.isFinite(start) && Number.isFinite(end) && end > start;
  inspectObject("GPU correlation record", row, {
    before: hasRange ? (
      <div className="context-actions">
        <button id="gpu-external-show-record" onClick={() => setRange(start, end)}>
          Show recorded operation
        </button>
      </div>
    ) : null,
  });
}

export function ExternalMappingDetails({ row }: { row: ExternalMapping }) {
  return (
    <>
      <h3>{`${row.externalKindName || row.externalKind} · ${row.externalId}`}</h3>
      <p>{`Internal correlation: ${row.correlationId} · ${row.status}`}</p>
      <p>{`Mapping recorded: ${duration(row.time)} · ${locName(row.location)}`}</p>
      <p>
        External IDs can describe ranges containing several API calls and device activities. This
        mapping does not prove a completion dependency.
      </p>
      {row.partial && <p className="analysis-warning">The record preview is incomplete.</p>}
      <div className="context-actions">
        <button
          id="gpu-external-export"
          onClick={() => download("gpu-external-mapping.json", JSON.stringify(row, null, 2))}
        >
          Export mapping evidence
        </button>
      </div>
      {SECTIONS.map(([kind, title, maxHeight]) => {
        const rows = row[`${kind}Records`] ?? EMPTY_RECORDS;
        return (
          <Fragment key={kind}>
            <h3>{title}</h3>
            <p>{`${num(rows.length, 0)} / ${num(row[`${kind}RecordTotal`] ?? rows.length, 0)} shown`}</p>
            <DataTable
              id={`gpu-${kind}-records`}
              rows={rows}
              columns={COLUMNS}
              onRow={inspectRecord}
              maxHeight={maxHeight}
            />
          </Fragment>
        );
      })}
    </>
  );
}
