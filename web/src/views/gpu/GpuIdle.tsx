import { useMemo } from "react";
import { Chart } from "../../components/chart/Chart";
import { ControlBar } from "../../components/controls/ControlBar";
import { buttonControl, selectControl } from "../../components/controls/factories";
import { Card } from "../../components/panel/Card";
import { DataTable } from "../../components/table/DataTable";
import { col, timeCol } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import { AnalysisDiagnostics } from "../../components/ui/AnalysisDiagnostics";
import { download } from "../../lib/download";
import { num } from "../../lib/format/numbers";
import { inspectObject } from "../../state/inspection";
import { locName } from "../../state/selectors";
import { getState } from "../../state/store";
import type { ViewState } from "../../state/types";
import { updateQuery } from "../shared/dataControls";
import { drawIdle } from "./drawIdle";
import type { IdleLevel, IdleResult, NamedIdleRow } from "./types";

const NOTES: Record<string, string> = {
  "unverified-device-topology":
    "These streams lack the device topology required for hardware grouping and are omitted.",
  "nonmonotonic-stack-time": "Ordinary function records move backwards in time.",
  "mismatched-stack-leave": "A function exit does not match its active entry.",
  "unmatched-stack-leave": "A function exit has no active entry.",
  "cyclic-calling-context": "A calling-context parent chain contains a cycle.",
  "missing-calling-context": "A recorded calling context has no definition.",
};
const LEVELS = [
  ["devices", "Physical device"],
  ["contexts", "GPU context"],
  ["locations", "Stream"],
] as const;
const MODES = [
  [0, "All events"],
  [1, "Explicit events"],
  [2, "Samples"],
] as const;
const EMPTY_ROWS: NamedIdleRow[] = [];
const VALUES: ColumnDef<NamedIdleRow>[] = [
  { key: "members", label: "Streams", number: true },
  timeCol("duration", "Selected window"),
  timeCol("active", "Function activity union"),
  timeCol("idle", "Idle time"),
  {
    ...col<NamedIdleRow>("idlePercentage", "Idle %", (row) =>
      row.idlePercentage == null ? "—" : num(row.idlePercentage, 3) + "%",
    ),
    number: true,
  },
];
const COLUMNS: Record<IdleLevel, ColumnDef<NamedIdleRow>[]> = {
  devices: [col("name", "Device"), ...VALUES],
  contexts: [col("name", "Context"), ...VALUES],
  locations: [col("name", "Stream"), ...VALUES],
};

export function GpuIdle({ result, snapshot }: { result: IdleResult; snapshot: ViewState }) {
  const level =
    snapshot.gpuIdleLevel === "contexts" || snapshot.gpuIdleLevel === "locations"
      ? snapshot.gpuIdleLevel
      : "devices";
  const mode =
    snapshot.gpuIdleEventMode === 1 || snapshot.gpuIdleEventMode === 2
      ? snapshot.gpuIdleEventMode
      : 0;
  const rows = useMemo(() => {
    if (result.status !== "fulfilled") return EMPTY_ROWS;
    return (result.value[level] || EMPTY_ROWS).map((row) => {
      const device = result.value.devices.find(
        (item) => item.key[1] === row.key[1] && item.key[2] === row.key[2],
      );
      return {
        ...row,
        name:
          level === "locations"
            ? locName(row.location)
            : level === "contexts"
              ? `${device?.name || "Device " + row.key[1]} · context ${row.key[0]}`
              : row.name || "",
        members: row.locations?.length ?? 1,
      };
    });
  }, [result, level]);
  return (
    <Card
      title="GPU idle statistics"
      caption={
        <span>
          Idle is the selected window minus the union of selected function activity. Device and
          context rows merge their streams before calculating idle time. RMA copy and message
          intervals are excluded; see Device occupancy for recorded kernel and copy activity.
          Function and location filters apply.
        </span>
      }
    >
      <ControlBar
        controls={[
          selectControl("gpu-idle-level", "Group by", level, LEVELS, (value) =>
            updateQuery({ gpuIdleLevel: value }),
          ),
          selectControl("gpu-idle-mode", "Calling-context events", mode, MODES, (value) =>
            updateQuery({ gpuIdleEventMode: Number(value) }),
          ),
          buttonControl(
            "gpu-idle-export",
            "Export idle statistics",
            () => {
              if (result.status !== "fulfilled") return;
              const { meta, region, exclude, group, locations } = getState();
              download(
                "gpu-idle-statistics.json",
                JSON.stringify(
                  {
                    trace: meta?.path,
                    filters: { region, exclude, group, locations: [...locations] },
                    ...result.value,
                  },
                  null,
                  2,
                ),
              );
            },
            { disabled: result.status !== "fulfilled" },
          ),
        ]}
      />
      {result.status === "rejected" ? (
        <p className="analysis-warning" role="alert">
          {result.reason instanceof Error ? result.reason.message : String(result.reason)}
        </p>
      ) : (
        <>
          <p className="muted">{`Activity source: ${result.value.sessionProducer === "StateTree" ? "calling-context records across the trace" : "instrumented function entries and exits"}.`}</p>
          <AnalysisDiagnostics
            summary="Idle statistics notes"
            open
            data={{
              diagnostics: result.value.diagnostics?.map((note) => ({
                ...note,
                message:
                  NOTES[note.code] || "Inspect the source records for this adapter diagnostic.",
              })),
            }}
          />
        </>
      )}
      <div className="chart-wrap">
        <Chart
          id="gpu-idle-chart"
          aria-label={`GPU idle percentage by ${level}`}
          draw={(element) => drawIdle(element, rows, result.status === "rejected")}
          deps={[rows, result.status]}
        />
      </div>
      <DataTable
        id="gpu-idle-table"
        rows={rows}
        columns={COLUMNS[level]}
        onRow={(row) => {
          if (result.status !== "fulfilled") return;
          const { source, start, end, eventMode, sessionProducer, diagnostics } = result.value;
          inspectObject("GPU idle statistics · " + row.name, {
            ...row,
            source,
            start,
            end,
            eventMode,
            sessionProducer,
            diagnostics,
          });
        }}
      />
    </Card>
  );
}
