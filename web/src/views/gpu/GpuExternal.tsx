import { Card } from "../../components/panel/Card";
import { DataTable } from "../../components/table/DataTable";
import { col, timeCol } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import { num } from "../../lib/format/numbers";
import { inspectObject } from "../../state/inspection";
import { locName } from "../../state/selectors";
import { RelationshipPager } from "../dependencies/RelationshipPager";
import type { RelationshipData } from "../dependencies/types";
import { ExternalMappingDetails } from "./ExternalMappingDetails";
import type { ExternalMapping } from "./types";

const EMPTY_MAPPINGS: ExternalMapping[] = [];
let inspection = 0;
const COLUMNS: ColumnDef<ExternalMapping>[] = [
  col("externalKindName", "External kind", (row) => row.externalKindName || row.externalKind),
  col("externalId", "External ID"),
  col("correlationId", "Internal correlation ID"),
  col("location", "Recording rank / thread", (row) => locName(row.location)),
  timeCol("time", "Recorded", false),
  col("internalRecordTotal", "API / device records"),
  col("status", "State"),
];

export function GpuExternal({ data, offset }: { data: RelationshipData; offset: number }) {
  if (!data.externalMappingTotal && !data.externalMappingInvalidRecords) return null;
  const rows = data.externalMappings ?? EMPTY_MAPPINGS;
  const start = data.externalMappingOffset || 0;
  return (
    <Card
      title="External GPU correlation mappings"
      tools={
        <RelationshipPager
          field="gpuExternalOffset"
          offset={offset}
          more={!!data.externalMappingMore}
        >
          {`${num(start, 0)}–${num(start + rows.length, 0)} / ${num(data.externalMappingTotal || 0, 0)}`}
        </RelationshipPager>
      }
      caption={
        <span>
          A recorded external range can map to several GPU invocations. These are identifier
          associations; they do not establish a launch, a wait or an unrecorded device interval.
        </span>
      }
    >
      {data.externalMappingPartial && (
        <p className="analysis-warning">
          Mapping collection is incomplete; omitted records can change an association.
        </p>
      )}
      <DataTable
        id="gpu-external-table"
        rows={rows}
        columns={COLUMNS}
        maxHeight={350}
        onRow={(row) =>
          inspectObject("External GPU mapping evidence", row, {
            before: <ExternalMappingDetails key={++inspection} row={row} />,
          })
        }
      />
    </Card>
  );
}
