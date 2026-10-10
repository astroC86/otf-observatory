import { useMemo } from "react";
import { addBookmark } from "../../state/bookmarks";
import { inspectObject } from "../../state/inspection";
import { num } from "../../lib/format/numbers";
import { persistState } from "../../state/persistence";
import { scheduleRender, setView } from "../../state/viewActions";
import { setRange } from "../../state/rangeActions";
import { Card } from "../../components/panel/Card";
import { DataTable } from "../../components/table/DataTable";
import { timeCol } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import { useExport } from "../../hooks/useExport";
import { updateState } from "../../state/store";
import type { AppState, ViewState } from "../../state/types";
import type { MarkerRow, MarkersResponse } from "../../api/types/data";
import { buttonControl } from "../../components/controls/factories";

const markerColumns: ColumnDef<MarkerRow>[] = [
  { key: "name", label: "Marker" },
  timeCol<MarkerRow>("time", "Time"),
  timeCol<MarkerRow>("duration", "Duration"),
  { key: "category", label: "Category" },
  { key: "severity", label: "Severity" },
];

type IndexedBookmark = AppState["bookmarks"][number] & {
  readonly index: number;
};
export function MarkersPanel({
  recorded,
  snapshot,
}: {
  recorded: MarkersResponse;
  snapshot: ViewState;
}) {
  useExport(recorded, "trace-markers");
  const bookmarks = useMemo(
    () => snapshot.bookmarks.map((row, index) => ({ ...row, index })),
    [snapshot.bookmarks],
  );
  const columns = useMemo<ColumnDef<IndexedBookmark>[]>(
    () => [
      { key: "name", label: "Bookmark" },
      timeCol<IndexedBookmark>("start", "Start"),
      timeCol<IndexedBookmark>("end", "End"),
      {
        key: "locations",
        label: "Locations",
        number: true,
        render: (_, row) => num(row.locations.length, 0),
      },
      {
        key: "index",
        label: "",
        render: (_, row) => (
          <button
            data-delete-bookmark={row.index}
            aria-label="Delete bookmark"
            onClick={(event) => {
              event.stopPropagation();
              updateState((previous) => ({
                bookmarks: previous.bookmarks.filter((_, index) => index !== row.index),
              }));
              persistState("bookmarks");
              scheduleRender();
            }}
          >{`×`}</button>
        ),
      },
    ],
    [],
  );
  return (
    <>
      <Card
        title="Selection bookmarks"
        controls={[buttonControl("add-bookmark", "＋ Bookmark current interval", addBookmark)]}
        caption={
          <span>{`Bookmarks and session settings are stored in this browser. Export a session to move them to another browser.`}</span>
        }
      >
        <DataTable
          id="bookmark-table"
          rows={bookmarks}
          columns={columns}
          onRow={(row) => {
            updateState({ locations: new Set(row.locations) });

            setRange(row.start, row.end);
            setView("timeline");
          }}
        />
      </Card>
      <Card title="Recorded trace markers">
        <DataTable
          id="marker-table"
          rows={recorded}
          columns={markerColumns}
          onRow={(row) => {
            inspectObject(row.name, row);
            setRange(
              row.time,
              row.time + Math.max(row.duration ?? 0, (snapshot.end - snapshot.start) / 20),
            );
          }}
        />
      </Card>
    </>
  );
}
