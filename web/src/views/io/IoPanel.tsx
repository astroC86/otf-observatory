import { useMemo } from "react";
import { inspectObject } from "../../state/inspection";
import { num } from "../../lib/format/numbers";
import { Card } from "../../components/panel/Card";
import { Chart } from "../../components/chart/Chart";
import { DataTable } from "../../components/table/DataTable";
import { EmptyState } from "../../components/ui/EmptyState";
import { bytesCol, countCol, timeCol } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import { useExport } from "../../hooks/useExport";
import type { ViewState } from "../../state/types";
import type {
  ResourceOperationRow,
  ResourceResponse,
  ResourceSummaryRow,
} from "../../api/types/data";
import { updateQuery } from "../shared/dataControls";
import { locationCol } from "../shared/locationCol";
import { selectControl } from "../../components/controls/factories";

const resourceColumns: ColumnDef<ResourceOperationRow>[] = [
  locationCol<ResourceOperationRow>(),
  { key: "operation", label: "Operation" },
  timeCol<ResourceOperationRow>("start", "Start"),
  timeCol<ResourceOperationRow>("end", "End"),
  bytesCol<ResourceOperationRow>("bytes", "Bytes"),
  { key: "status", label: "Status" },
];

export function IoPanel({ data, snapshot }: { data: ResourceResponse; snapshot: ViewState }) {
  useExport(data.rows, `${snapshot.ioMode}-operations`);
  const columns = useMemo<ColumnDef<ResourceSummaryRow>[]>(
    () => [
      ...(snapshot.ioMode === "io"
        ? [
            {
              key: "file",
              label: "File",
              render: (_: unknown, row: ResourceSummaryRow) =>
                `${snapshot.meta.files[String(row.file)] || row.file || ""}`,
            },
          ]
        : []),
      { key: "operation", label: "Operation" },
      countCol<ResourceSummaryRow>("count", "Count"),
      timeCol<ResourceSummaryRow>("duration", "Duration"),
      bytesCol<ResourceSummaryRow>("bytes", "Bytes"),
    ],
    [snapshot.ioMode, snapshot.meta.files],
  );
  return (
    <>
      <Card
        title="Shared resource timeline"
        controls={[
          selectControl(
            "io-mode",
            undefined,
            snapshot.ioMode,
            [
              ["io", "File I/O"],
              ["rma", "RMA operations"],
            ],
            (value) => updateQuery({ ioMode: value }),
            {
              ariaLabel: "Shared resource type",
            },
          ),
        ]}
        caption={<span>{`${num(data.total, 0)} operations · Showing at most 3,000 records.`}</span>}
      >
        {data.rows.length ? (
          <div className="chart-wrap">
            <Chart
              id="resource-chart"
              aria-label="Shared resource operations"
              spec={{ type: "resources", data }}
            />
          </div>
        ) : (
          <EmptyState
            title={`No ${snapshot.ioMode === "io" ? "I/O" : "RMA"} operations in this selection`}
            detail={
              snapshot.ioMode === "io"
                ? "I/O calls may appear as regions even when the producer did not record I/O operation events."
                : "This archive may not contain one-sided communication events."
            }
          />
        )}
      </Card>
      <Card title="Resource summary">
        <DataTable
          id="io-summary"
          rows={data.summary}
          columns={columns}
          onRow={(row) => inspectObject(row.operation, row)}
        />
      </Card>
      <Card title="Operation records">
        <DataTable
          id="io-table"
          rows={data.rows}
          columns={resourceColumns}
          onRow={(row) => inspectObject(row.operation, row)}
        />
      </Card>
    </>
  );
}
