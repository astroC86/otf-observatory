import { useMemo } from "react";
import { Card } from "../../components/panel/Card";
import { DataTable } from "../../components/table/DataTable";
import { AnalysisDiagnostics } from "../../components/ui/AnalysisDiagnostics";
import { StatGrid } from "../../components/ui/StatGrid";
import { useEmbedHidden } from "../../embed/useEmbedHidden";
import { useExport } from "../../hooks/useExport";
import { compact, num } from "../../lib/format/numbers";
import { duration } from "../../lib/format/time";
import type { ViewState } from "../../state/types";
import { GpuClocks } from "../gpu/GpuClocks";
import { GpuExternal } from "../gpu/GpuExternal";
import { GpuIdle } from "../gpu/GpuIdle";
import { TaskWaits } from "../waits/TaskWaits";
import { Chart } from "../../components/chart/Chart";
import { RelationshipControls } from "./RelationshipControls";
import { RelationshipPager } from "./RelationshipPager";
import { candidateColumns, deviceColumns, edgeColumns, intervalColumns } from "./columns";
import { inspectAnalysisEvidence } from "./inspect";
import { EMPTY_RECORDS, type RelationshipResult } from "./types";

export function RelationshipPanel({
  result,
  snapshot,
}: {
  result: RelationshipResult;
  snapshot: ViewState;
}) {
  const { kind, data } = result;
  const gpu = kind === "gpu";
  const all = data.intervals ?? EMPTY_RECORDS;
  const nodes = data.nodes ?? EMPTY_RECORDS;
  const edges = data.edges ?? EMPTY_RECORDS;
  const selected = snapshot.relationshipKind[kind] || "";
  const search = snapshot.relationshipSearch;
  const hidden = useEmbedHidden();
  const chartEdges =
    snapshot.relationshipEdges === false ? EMPTY_RECORDS : (data.timelineEdges ?? edges);
  const { kinds, intervals, keptNodes } = useMemo(() => {
    const needle = search.toLowerCase();
    const intervals = all.filter(
      (row) =>
        (!selected || row.kind === selected) &&
        (!search || JSON.stringify(row).toLowerCase().includes(needle)),
    );
    // Drawn arrows need both endpoint nodes, even when the search matched only the edge.
    const endpoints = new Set(
      chartEdges.flatMap((edge) => [String(edge.source), String(edge.target)]),
    );
    return {
      intervals,
      kinds:
        data.availableKinds ??
        [...new Set(all.flatMap((row) => (row.kind ? [row.kind] : [])))].toSorted(),
      keptNodes: nodes.filter(
        (node) =>
          !search ||
          endpoints.has(String(node.id)) ||
          JSON.stringify(node).toLowerCase().includes(needle) ||
          intervals.some((row) => Array.isArray(row.evidence) && row.evidence.includes(node.event)),
      ),
    };
  }, [all, nodes, chartEdges, data.availableKinds, selected, search]);
  const timeline = data.timelineIntervals ?? intervals;
  const count = new Set([...timeline, ...keptNodes].map((row) => row.location)).size;
  const page = Math.min(snapshot.analysisPage, Math.max(0, Math.ceil(count / 24) - 1));
  const totals: [string, number, string?][] = [
    [
      gpu ? "Recorded kernels" : "Reconstructed intervals",
      gpu
        ? (data.summary?.kernels ?? all.filter((row) => row.kind === "kernel").length)
        : (data.summary?.intervals ?? all.length),
    ],
    [
      gpu ? "Memory operations" : "Dependency edges",
      gpu
        ? (data.summary?.copies ?? all.filter((row) => String(row.kind).includes("copy")).length)
        : (data.summary?.edges ?? edges.length),
    ],
    ["Locations", count],
    ["Evidence events", data.scannedEvents || nodes.length, "Selected analysis record families"],
  ];
  const devices = data.devices ?? data.summary?.devices ?? EMPTY_RECORDS;
  const candidates = data.correlationCandidates ?? EMPTY_RECORDS;
  const tables = [
    {
      show: gpu,
      id: "device-table",
      title: "Device occupancy",
      rows: Array.isArray(devices) ? devices : Object.values(devices),
      columns: deviceColumns,
      maxHeight: 590,
      tools: null,
      caption:
        "Busy time is the union of recorded kernel and copy intervals. Uninstrumented device work is not included.",
    },
    {
      show: true,
      id: "relationship-table",
      title: "Recorded intervals",
      rows: intervals,
      columns: intervalColumns,
      maxHeight: 590,
      tools: (
        <RelationshipPager
          field="relationshipOffset"
          offset={snapshot.relationshipOffset}
          more={!!data.more}
        >
          {`Record offset ${num(snapshot.relationshipOffset, 0)}`}
        </RelationshipPager>
      ),
      caption: `${num(intervals.length, 0)} / ${num(data.intervalTotal ?? intervals.length, 0)} matching intervals${data.truncated ? " · scan limit reached" : ""}. Tables are paged; timeline coverage is independent of the table page.`,
    },
    {
      show: true,
      id: "edge-table",
      title: "Dependency evidence",
      rows: edges,
      columns: edgeColumns,
      maxHeight: 400,
      tools: null,
      caption: `${num(edges.length, 0)} / ${num(data.edgeTotal ?? edges.length, 0)} matching edges · click a row to inspect the records establishing a relationship.`,
    },
    {
      show: gpu && !!data.correlationCandidateTotal,
      id: "gpu-candidates",
      title: "Unresolved host/device associations",
      rows: candidates,
      columns: candidateColumns,
      maxHeight: 320,
      tools: null,
      caption: `${num(candidates.length, 0)} / ${num(data.correlationCandidateTotal, 0)} candidate pairs share a recorded identifier. These are alternatives, not established launch or copy dependencies.`,
    },
  ];
  useExport(intervals, `${kind}-intervals`);
  return (
    <>
      <StatGrid
        items={totals.map(([label, value, detail]) => ({ label, value: compact(value), detail }))}
      />
      <Card
        title={gpu ? "Device & host timeline" : "Causal dependency timeline"}
        tools={
          <RelationshipPager field="analysisPage" offset={page} more={(page + 1) * 24 < count}>
            {`Locations ${count ? Math.min(page * 24 + 1, count) : 0}–${Math.min((page + 1) * 24, count)} / ${count}`}
          </RelationshipPager>
        }
        caption={
          <span>{`${gpu ? "Host/kernel links use recorded correlation identifiers. Transfer intervals use their recorded completion events." : "Arrows represent recorded ownership, lifecycle or task relationships. Inferred associations are labeled in the evidence."} ${data.displayReduction && data.displayReduction !== "none" ? "Dense charts sample recorded intervals across the full range; zoom for detail." : ""} Drag to zoom; select an interval for source records.`}</span>
        }
      >
        <RelationshipControls snapshot={snapshot} kinds={kinds} />
        <div className="chart-wrap">
          <Chart
            id="relationship-chart"
            aria-label={`${gpu ? "GPU correlation" : "Thread task and lock dependency"} timeline`}
            spec={{
              type: "relationships",
              intervals: timeline,
              edges: chartEdges,
              nodes: keptNodes,
              page,
              onEvidence: inspectAnalysisEvidence,
            }}
          />
        </div>
      </Card>
      {!gpu && data.threadLockAnalysis && (
        <p
          id="thread-lock-graph-summary"
          className="filter-line"
          data-embed-hidden={hidden || undefined}
        >
          {`Thread-lock availability: ${duration(data.threadLockAnalysis.required)} required · ${duration(data.threadLockAnalysis.conditional)} conditional, unioned per waiting thread. Select a contention edge to inspect its owner and affected acquisition.`}
        </p>
      )}
      <AnalysisDiagnostics data={data} />
      {result.kind === "gpu" ? (
        <>
          <GpuIdle result={result.idle} snapshot={snapshot} />
          {data.clockProvenance && <GpuClocks clocks={data.clockProvenance} />}
          <GpuExternal data={data} offset={snapshot.gpuExternalOffset} />
        </>
      ) : (
        <TaskWaits intervals={intervals} analysis={data.taskAnalysis} />
      )}
      {tables
        .filter((table) => table.show)
        .map(({ title, caption, tools, show, ...table }) => (
          <Card key={table.id} title={title} caption={<span>{caption}</span>} tools={tools}>
            <DataTable {...table} onRow={inspectAnalysisEvidence} />
          </Card>
        ))}
    </>
  );
}
