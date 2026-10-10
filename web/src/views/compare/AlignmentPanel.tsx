import { useMemo } from "react";
import { Card } from "../../components/panel/Card";
import {
  buttonControl as button,
  selectControl as select,
} from "../../components/controls/factories";
import { DataTable } from "../../components/table/DataTable";
import { Chart } from "../../components/chart/Chart";
import { StatGrid } from "../../components/ui/StatGrid";
import { AnalysisDiagnostics } from "../../components/ui/AnalysisDiagnostics";
import { useEmbedHidden } from "../../embed/useEmbedHidden";
import { compact, num } from "../../lib/format/numbers";
import { duration } from "../../lib/format/time";
import { getState, updateState } from "../../state/store";
import { useStore } from "../../state/useStore";
import { updateQuery } from "../shared/dataControls";
import { inspectAnchor } from "./actions";
import { anchorColumns, ambiguityColumns, mappingOptions } from "./columns";
import { drawAnchors } from "./drawAnchors";
import type { Alignment } from "./types";

export function AlignmentPanel({
  alignment,
  traceDuration,
}: {
  alignment: Alignment;
  traceDuration: number;
}) {
  const hidden = useEmbedHidden();
  const { mode, applied } = useStore((state) => ({
    mode: state.alignmentMode || "affine",
    applied: state.alignmentApplied,
  }));
  const quality = alignment.quality;
  const ambiguities = useMemo(
    () =>
      (alignment.ambiguities || []).flatMap((group) =>
        group.candidates.map((pair) => ({ ...pair, rank: group.rank })),
      ),
    [alignment],
  );
  return (
    <>
      <StatGrid
        items={[
          {
            label: "Matched anchors",
            value: compact(quality.matched ?? alignment.matches?.length),
          },
          {
            label: "Phase correspondence",
            value: `${num((quality.correspondenceConfidence ?? quality.confidence ?? 0) * 100, 1)}%`,
            detail: `Heuristic score; global affine fit: ${quality.level || "unknown"}`,
          },
          {
            label: "Median residual",
            value: duration(quality.residualMedian),
            detail: `95th percentile: ${duration(quality.residualP95)}`,
          },
          {
            label: "Anchor coverage",
            value: `${num((quality.coverageA || 0) * 100, 1)}% / ${num((quality.coverageB || 0) * 100, 1)}%`,
            detail: "Baseline / comparison",
          },
        ]}
      />
      {quality.level === "low" && (
        <p className="analysis-warning" data-embed-hidden={hidden || undefined}>
          {
            "Alignment evidence is limited. Inspect matched phases and residuals before applying the mapping. Piecewise alignment can follow differing phase durations, but does not imply equal iteration counts or equal work."
          }
        </p>
      )}
      <Card
        title="Automatic alignment evidence"
        controls={[
          select("alignment-mode", "Mapping", mode, mappingOptions, (value) =>
            (getState().alignmentApplied ? updateQuery : updateState)({ alignmentMode: value }),
          ),
          button(
            "alignment-apply",
            "Apply proposed alignment",
            () =>
              updateQuery({
                shift: alignment.shift,
                alignmentScale: alignment.scale,
                alignmentApplied: true,
              }),
            { className: "primary", disabled: !alignment.matches?.length },
          ),
        ]}
        caption={
          <span>{`${alignment.method || "Semantic anchors"} · proposed offset ${duration(alignment.shift)}, scale ${num(alignment.scale, 8)} · ${applied ? "Applied" : "Preview"}`}</span>
        }
      >
        <div className="chart-wrap">
          <Chart
            id="alignment-chart"
            aria-label="Cross run anchor matches"
            draw={(element) => drawAnchors(element, alignment, traceDuration)}
            deps={[alignment, traceDuration]}
          />
        </div>
      </Card>
      <AnalysisDiagnostics data={alignment} />
      <Card title="Matched anchors">
        <DataTable
          id="alignment-table"
          rows={alignment.matches || []}
          columns={anchorColumns}
          onRow={inspectAnchor}
          maxHeight={280}
        />
      </Card>
      {ambiguities.length > 0 && (
        <Card
          title="Unresolved phase correspondences"
          caption={
            <span>
              {
                "These alternatives do not affect the mapping. Inspect their evidence and add explicit anchor pairs to resolve them."
              }
            </span>
          }
        >
          <DataTable
            id="alignment-ambiguities"
            rows={ambiguities}
            columns={ambiguityColumns}
            onRow={inspectAnchor}
            maxHeight={240}
          />
        </Card>
      )}
    </>
  );
}
