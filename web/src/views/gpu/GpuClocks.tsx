import { Card } from "../../components/panel/Card";
import { buttonControl } from "../../components/controls/factories";
import { DataTable } from "../../components/table/DataTable";
import { col } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import { download } from "../../lib/download";
import { inspectObject } from "../../state/inspection";
import { locName } from "../../state/selectors";
import type { ClockLocation, ClockProvenance } from "./types";

const LABELS: Record<string, string> = {
  "recorded-linear-offsets": "Recorded clock calibration",
  "single-offset-no-interval": "Single sample; no correction interval",
  "no-local-offsets": "No local clock offsets recorded",
  "provenance-unavailable": "Calibration metadata unavailable in this index",
};
const EMPTY_LOCATIONS: ClockLocation[] = [];
const COLUMNS: ColumnDef<ClockLocation>[] = [
  col("location", "Rank / thread / stream", (row) => locName(row.location)),
  col("status", "Calibration evidence", (row) => LABELS[row.status] || row.status),
  col("samples", "Samples", (row) => row.samples?.length || 0),
  col("intervals", "Correction intervals", (row) => row.intervals?.length || 0),
];

export function GpuClocks({ clocks }: { clocks: ClockProvenance }) {
  const status =
    clocks.correctionsApplied === true
      ? "The OTF2 reader applied recorded clock corrections before analysis."
      : clocks.correctionsApplied === false
        ? "The reader reports no clock correction."
        : "This index does not retain the reader’s clock-correction provenance.";
  return (
    <Card
      title="Host / device clock calibration"
      controls={[
        buttonControl("gpu-clock-export", "Export clock calibration", () =>
          download("gpu-clock-calibration.json", JSON.stringify(clocks, null, 2)),
        ),
      ]}
      caption={
        <span>
          Click a location for its original calibration ticks, offsets and standard deviations.
          Event timestamps are corrected once; the viewer does not fit an extra shift from nearby
          host/device events.
        </span>
      }
    >
      <p className="filter-line">{status}</p>
      <details className="metric-help">
        <summary>Inspect location clocks</summary>
        <p>{clocks.eventTimeDomain}</p>
        <p>{clocks.interpolation}</p>
        <DataTable
          id="gpu-clock-table"
          rows={clocks.locations || EMPTY_LOCATIONS}
          columns={COLUMNS}
          onRow={(row) => inspectObject("Clock calibration · " + locName(row.location), row)}
          maxHeight={300}
        />
        <p>{clocks.uncertainty}</p>
      </details>
    </Card>
  );
}
