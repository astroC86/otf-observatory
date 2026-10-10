import { memo, useMemo } from "react";
import { Card } from "../../components/panel/Card";
import { DataTable } from "../../components/table/DataTable";
import { EmptyState } from "../../components/ui/EmptyState";
import { AnalysisDiagnostics } from "../../components/ui/AnalysisDiagnostics";
import { duration } from "../../lib/format/time";
import { useExport } from "../../hooks/useExport";
import { AlignmentPanel } from "./AlignmentPanel";
import { comparisonColumns } from "./columns";
import { inspectEvidence } from "./actions";
import { projectProfiles } from "./profiles";
import type { ComparisonProps } from "./types";

export const ComparisonResults = memo(function ComparisonResults({
  data,
  snapshot,
}: ComparisonProps) {
  const ensemble = snapshot.ensemble?.baseline.id === snapshot.id ? snapshot.ensemble : null;
  const { result, ensembleResult } = data;
  const profiles = useMemo(() => projectProfiles(ensembleResult, true), [ensembleResult]);
  useExport<object>(
    ensembleResult ? profiles.rows : result?.rows || profiles.rows,
    ensembleResult ? "multi-run-profiles" : "trace-comparison",
    Boolean(ensembleResult || result),
  );
  return (
    <>
      {ensemble && <AnalysisDiagnostics data={ensemble} />}
      {ensembleResult && (
        <Card
          title="Function profiles across runs"
          caption={<span>{ensembleResult.durationSemantics}</span>}
        >
          <DataTable id="ensemble-profiles" {...profiles} onRow={inspectEvidence} />
        </Card>
      )}
      {snapshot.alignment && (
        <AlignmentPanel alignment={snapshot.alignment} traceDuration={snapshot.meta.duration} />
      )}
      <Card
        title="Function profile changes"
        caption={
          result && (
            <span>{`Baseline ${duration(result.rangeA[0])}–${duration(result.rangeA[1])} · comparison ${duration(result.rangeB[0])}–${duration(result.rangeB[1])}. Positive deltas indicate more time in the comparison run.`}</span>
          )
        }
      >
        {result ? (
          <DataTable
            id="comparison-table"
            rows={result.rows}
            columns={comparisonColumns}
            onRow={inspectEvidence}
          />
        ) : (
          <EmptyState
            title="Choose a loaded comparison trace"
            detail="Match recorded functions or markers automatically, or apply an explicit offset."
          />
        )}
      </Card>
    </>
  );
});
