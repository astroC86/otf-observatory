import { inspectObject } from "../../state/inspection";
import { num } from "../../lib/format/numbers";
import { Card } from "../../components/panel/Card";
import { ControlBar } from "../../components/controls/ControlBar";
import { DataTable } from "../../components/table/DataTable";
import { countCol, timeCol } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import { useExport } from "../../hooks/useExport";
import type { ViewState } from "../../state/types";
import type { EventRow, EventsResponse } from "../../api/types/data";
import { pageButton } from "../shared/dataControls";
import { locationCol } from "../shared/locationCol";
import { EventFilters } from "./EventFilters";

const eventColumns: ColumnDef<EventRow>[] = [
  countCol<EventRow>("id", "Record"),
  timeCol<EventRow>("time", "Time"),
  locationCol<EventRow>(),
  { key: "kind", label: "Event type" },
  { key: "tick", label: "Original tick", number: true },
  {
    key: "data",
    label: "Fields",
    render: (_, row) => <span className="definition-data">{`${JSON.stringify(row.data)}`}</span>,
  },
];

export function EventsPanel({ data, snapshot }: { data: EventsResponse; snapshot: ViewState }) {
  useExport(data.rows, "trace-events");
  return (
    <Card
      title="Trace event records"
      tools={
        <ControlBar
          className="pager"
          controls={[
            pageButton("events-prev", "eventOffset", -200, snapshot.eventOffset === 0),
            {
              kind: "content",
              children: (
                <span>{`Rows ${num(snapshot.eventOffset + 1, 0)}–${num(snapshot.eventOffset + data.rows.length, 0)}`}</span>
              ),
            },
            pageButton("events-next", "eventOffset", 200, !data.more),
          ]}
        />
      }
      caption={
        <span>{`Original integer clock ticks and IDs are preserved. Click a record for complete fields and attributes.`}</span>
      }
    >
      <EventFilters snapshot={snapshot} />
      <DataTable
        id="events-table"
        rows={data.rows}
        columns={eventColumns}
        onRow={(row) => inspectObject(row.kind, row)}
      />
    </Card>
  );
}
