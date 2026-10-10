import { useEffect, useMemo } from "react";
import { Card } from "../../components/panel/Card";
import { ControlBar } from "../../components/controls/ControlBar";
import { selectControl } from "../../components/controls/factories";
import { StatGrid } from "../../components/ui/StatGrid";
import { AnalysisDiagnostics } from "../../components/ui/AnalysisDiagnostics";
import { useExport } from "../../hooks/useExport";
import { compact } from "../../lib/format/numbers";
import { duration } from "../../lib/format/time";
import { updateState } from "../../state/store";
import type { ViewState } from "../../state/types";
import { updateQuery } from "../shared/dataControls";
import { Chart } from "../../components/chart/Chart";
import { inspectAnalysisEvidence } from "../dependencies/inspect";
import { WaitCauses } from "./causes/WaitCauses";
import { prepareCauses, causeGraph } from "./causes/prepare";
import { WaitEvidenceTables } from "./WaitEvidenceTables";
import { EMPTY, type WaitResponse } from "./types";

const SOURCES = [
  ["waits", "MPI messages, collectives & RMA locks"],
  ["synchronization", "Threads, locks, tasks & GPU synchronization"],
] as const;
const MPI_CATEGORIES = [
  "mpi_wait",
  "mpi_receive",
  "mpi_send",
  "mpi_test",
  "late_sender",
  "late_receiver",
  "late_sender_wait",
  "late_receiver_wait",
  "collective_arrival_skew",
];
const SYNC_CATEGORIES = [
  "thread_barrier",
  "lock_acquire",
  "thread_join",
  "task_wait",
  "gpu_synchronization",
];
const LEGEND = [
  ["#8799b4", "Observed call"],
  ["#3a83ce", "Required prerequisite unavailable"],
  ["#d78638", "Conditional delay / arrival estimate"],
].map(([color, text]) => ({
  kind: "content" as const,
  children: (
    <span className="legend-item">
      <i className="swatch" style={{ background: color }} />
      {text}
    </span>
  ),
}));

export function WaitsPanel({ data, snapshot }: { data: WaitResponse; snapshot: ViewState }) {
  const source = snapshot.waitSource || "waits",
    category = snapshot.waitCategory || "";
  const rows = data.rows || EMPTY;
  const visible = useMemo(
    () => rows.filter((row) => !category || row.category === category),
    [rows, category],
  );
  const causes = useMemo(() => prepareCauses(visible, data, source), [visible, data, source]);
  const graph = useMemo(() => causeGraph(causes), [causes]);
  const categories = useMemo(
    () => [
      ...new Set([
        ...MPI_CATEGORIES,
        ...(source === "synchronization" ? SYNC_CATEGORIES : []),
        ...(data.summary || EMPTY).map((row) => row.category || ""),
      ]),
    ],
    [source, data.summary],
  );
  const causeOffset = causes.pagination?.offset;
  useEffect(() => {
    if (causeOffset !== undefined) updateState({ waitCauseOffset: causeOffset });
  }, [causeOffset]);
  useExport(rows, "wait-analysis");
  const observed = data.totals?.observed ?? rows.reduce((sum, row) => sum + (row.observed || 0), 0);
  const inferred = data.totals?.inferred ?? rows.reduce((sum, row) => sum + (row.inferred || 0), 0);
  return (
    <>
      <ControlBar
        controls={[
          selectControl("wait-source", "Analysis source", source, SOURCES, (waitSource) =>
            updateQuery({
              waitSource,
              waitCategory: "",
              waitOffset: 0,
              waitCauseOffset: 0,
              waitRequestOffset: 0,
              waitCollectiveOffset: 0,
              waitProbeOffset: 0,
              waitRmaLockOffset: 0,
            }),
          ),
        ]}
      />
      <StatGrid
        items={[
          {
            label: "Observed routine time",
            value: duration(observed),
            detail: "Time inside instrumented communication or synchronization calls",
          },
          {
            label: "Estimated dependency delay",
            value: duration(inferred),
            detail: "Model estimate; blocked-time lower bound is zero",
          },
          { label: "Classified calls", value: compact(data.total ?? rows.length) },
          {
            label: "Collective instances",
            value: compact(data.totals?.collectiveCount ?? data.collectives?.length ?? 0),
            detail: "Participant arrivals grouped by communicator or team",
          },
        ]}
      />
      <Card
        title="Wait-state timeline"
        caption={
          <span>
            {
              "Arrows link enabling operations to affected calls. Colored segments show prerequisite availability or conditional estimates; they do not measure CPU blocked time. Timeline displays the first 24 locations of this page."
            }
          </span>
        }
      >
        <ControlBar
          controls={[
            selectControl(
              "wait-category",
              "Category",
              category,
              [["", "All categories"], ...categories],
              (waitCategory) => updateQuery({ waitCategory, waitOffset: 0, waitCauseOffset: 0 }),
            ),
            ...LEGEND,
          ]}
        />
        <div className="chart-wrap">
          <Chart
            id="wait-chart"
            aria-label="Wait state analysis timeline"
            spec={{
              type: "relationships",
              intervals: visible,
              ...graph,
              wait: true,
              onEvidence: inspectAnalysisEvidence,
            }}
          />
        </div>
      </Card>
      <AnalysisDiagnostics data={data} />
      <WaitCauses data={causes} />
      <WaitEvidenceTables
        data={data}
        visible={visible}
        mpi={source === "waits"}
        snapshot={snapshot}
      />
    </>
  );
}
