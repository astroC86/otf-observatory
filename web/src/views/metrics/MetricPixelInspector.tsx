import { useMemo, useState } from "react";
import { ControlBar } from "../../components/controls/ControlBar";
import { buttonControl, selectControl } from "../../components/controls/factories";
import { DataTable } from "../../components/table/DataTable";
import { AnalysisDiagnostics } from "../../components/ui/AnalysisDiagnostics";
import { download } from "../../lib/download";
import { PIXEL_COLUMNS } from "./columns";
import type { MetricPixel, MetricResult, PixelDetails } from "./types";

type DetailPanel = { kind: "pixel"; pixel: MetricPixel } | { kind: "sources" };
export function MetricPixelInspector({
  details,
  result,
}: {
  details: PixelDetails;
  result: MetricResult;
}) {
  const [stage, setStage] = useState("0");
  const [panels, setPanels] = useState<DetailPanel[]>([]);
  const [source, setSource] = useState(details);
  if (source !== details) {
    setSource(details);
    setStage("0");
    setPanels([]);
  }
  const pixels = details.timelines[Number(source === details ? stage : "0")]!.pixels;
  const rows = useMemo(() => pixels.slice(0, 1000), [pixels]);
  const stages = details.timelines.map(
    (timeline, i) =>
      [
        String(i),
        `${timeline.stage} · ${timeline.name || timeline.location} · ${timeline.operation}`,
      ] as const,
  );
  return (
    <>
      <p>Values include interval weighting and the recorded source attribution ranges.</p>
      <ControlBar
        className={null}
        controls={[selectControl("pixel-stage", "Stage", stage, stages, setStage)]}
      />
      <p
        id="pixel-count"
        className="muted"
      >{`${pixels.length} pixels. Showing the first ${Math.min(1000, pixels.length)}; export includes all returned evidence.`}</p>
      <DataTable
        key={stage}
        id="pixel-table"
        rows={rows}
        columns={PIXEL_COLUMNS}
        maxHeight={350}
        onRow={(pixel) =>
          setPanels((previous) => [
            ...previous.filter((panel) => panel.kind !== "pixel"),
            { kind: "pixel", pixel },
          ])
        }
      />
      <ControlBar
        className="context-actions"
        controls={[
          buttonControl("pixel-sources", "Inspect source identifiers", () =>
            setPanels((previous) =>
              previous.some((panel) => panel.kind === "sources")
                ? previous.filter((panel) => panel.kind !== "sources")
                : [...previous, { kind: "sources" }],
            ),
          ),
          buttonControl("pixel-export", "Export pixel evidence", () =>
            download("metric-pixel-evidence.json", JSON.stringify(details, null, 2)),
          ),
        ]}
      />
      <AnalysisDiagnostics data={result} />
      {panels.map((panel) => (
        <pre
          key={panel.kind}
          id={panel.kind === "pixel" ? "pixel-detail" : "pixel-source-detail"}
          className="code-block"
        >
          {JSON.stringify(panel.kind === "pixel" ? panel.pixel : details.sources, null, 2)}
        </pre>
      ))}
    </>
  );
}
