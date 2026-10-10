import { inspectObject } from "../../state/inspection";
import { num } from "../../lib/format/numbers";
import { Card } from "../../components/panel/Card";
import { DataTable } from "../../components/table/DataTable";
import { bytesCol, countCol, timeCol } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import { useExport } from "../../hooks/useExport";
import type {
  CollectiveRow,
  CollectiveSummaryRow,
  CollectivesResponse,
} from "../../api/types/data";
import { locationCol } from "../shared/locationCol";

const collectiveSummaryColumns: ColumnDef<CollectiveSummaryRow>[] = [
  { key: "operation", label: "Operation" },
  countCol<CollectiveSummaryRow>("count", "Participants / operations"),
  timeCol<CollectiveSummaryRow>("duration", "Total duration"),
  bytesCol<CollectiveSummaryRow>("bytes", "Bytes sent"),
  bytesCol<CollectiveSummaryRow>("received", "Bytes received"),
];
const collectiveColumns: ColumnDef<CollectiveRow>[] = [
  { key: "operation", label: "Operation" },
  locationCol<CollectiveRow>(),
  timeCol<CollectiveRow>("start", "Begin"),
  timeCol<CollectiveRow>("end", "End"),
  { key: "comm", label: "Communicator" },
  {
    key: "root",
    label: "Root",
    render: (_, row) => (row.root === "4294967295" ? "None" : `${row.root ?? ""}`),
  },
  bytesCol<CollectiveRow>("sent", "Sent"),
  bytesCol<CollectiveRow>("received", "Received"),
];

export function CollectivesPanel({ data }: { data: CollectivesResponse }) {
  useExport(data.rows, "collective-operations");
  return (
    <>
      <Card
        title="Collective operation summary"
        caption={
          <span>{`${num(data.total, 0)} participant operations. Duration is recorded locally on each participating location.`}</span>
        }
      >
        <DataTable
          id="collective-summary"
          rows={data.summary}
          columns={collectiveSummaryColumns}
          onRow={(row) => inspectObject(row.operation, row)}
        />
      </Card>
      <Card
        title="Collective operations"
        caption={
          <span>{`Showing ${num(data.rows.length, 0)} of ${num(data.total, 0)} records. Zoom in to inspect dense regions.`}</span>
        }
      >
        <DataTable
          id="collective-table"
          rows={data.rows}
          columns={collectiveColumns}
          onRow={(row) => inspectObject(row.operation, row)}
        />
      </Card>
    </>
  );
}
