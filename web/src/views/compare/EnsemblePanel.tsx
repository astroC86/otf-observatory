import { useMemo } from "react";
import { Card } from "../../components/panel/Card";
import { ControlBar } from "../../components/controls/ControlBar";
import {
  buttonControl as button,
  selectControl as select,
} from "../../components/controls/factories";
import { Chart } from "../../components/chart/Chart";
import { DataTable } from "../../components/table/DataTable";
import { download } from "../../lib/download";
import { getState, updateState } from "../../state/store";
import { useStore } from "../../state/useStore";
import { updateQuery } from "../shared/dataControls";
import { ensembleColumns, ensembleOptions } from "./columns";
import { drawAnchors } from "./drawAnchors";
import type { TraceListing } from "../../api/types/common";
import type { Ensemble } from "./types";

interface Props {
  archives: TraceListing[];
  ensemble: Ensemble | null;
  aligning: boolean;
  onAlign: () => void;
}

export function EnsemblePanel({ archives, ensemble, aligning, onAlign }: Props) {
  const { id, selected, mode, applied } = useStore((state) => ({
    id: state.id,
    selected: state.comparisonRuns,
    mode: state.ensembleMode,
    applied: state.ensembleApplied,
  }));
  const others = archives.filter((trace) => trace.id !== id);
  const rows = useMemo(
    () =>
      ensemble?.runs.map((run, index) => ({
        ...run,
        runNumber: index + 1,
        matched: run.alignment.quality.matched,
        status: run.alignment.quality.status,
        shift: run.alignment.shift,
        scale: run.alignment.scale,
        residual: run.alignment.quality.residualP95,
      })) || [],
    [ensemble],
  );
  return (
    <Card
      title="Compare multiple runs"
      caption={
        <span>
          {
            "Select up to 15 comparison runs. Each maps directly to the baseline. Select a result row to inspect or constrain that run."
          }
        </span>
      }
    >
      <div className="ensemble-picker">
        {others.length ? (
          others.map((trace) => (
            <label key={trace.id} className="check" title={trace.path || trace.name}>
              <input
                type="checkbox"
                data-comparison-run={trace.id}
                checked={selected.includes(trace.id)}
                onChange={(event) =>
                  updateQuery({
                    comparisonRuns: others
                      .filter((other) =>
                        other.id === trace.id
                          ? event.target.checked
                          : getState().comparisonRuns.includes(other.id),
                      )
                      .map((other) => other.id),
                    ensembleApplied: false,
                    ensemble: null,
                    markerSession: null,
                    markerWindow: null,
                  })
                }
              />
              <span>{trace.name}</span>
            </label>
          ))
        ) : (
          <p className="muted">Open another trace to add a comparison run.</p>
        )}
      </div>
      <ControlBar
        controls={[
          button(
            "align-many",
            aligning ? "Opening and aligning runs…" : "Align selected runs",
            onAlign,
            { className: "primary", disabled: aligning },
          ),
          select("ensemble-mode", "Mapping", mode, ensembleOptions, (value) =>
            (ensemble ? updateQuery : updateState)({ ensembleMode: value }),
          ),
          ...(ensemble
            ? [
                button(
                  "ensemble-apply",
                  applied ? "Mappings applied" : "Apply all mappings",
                  () => updateQuery({ ensembleApplied: true }),
                  { disabled: ensemble.runs.some((run) => !run.alignment.matches.length) },
                ),
                button("ensemble-export", "Export mappings", () =>
                  download(
                    "trace-alignment-mappings.json",
                    JSON.stringify({ ...ensemble, mode: getState().ensembleMode }, null, 2),
                  ),
                ),
              ]
            : []),
        ]}
      />
      {ensemble && (
        <>
          <div className="chart-wrap">
            <Chart
              id="ensemble-chart"
              aria-label="Multiple runs aligned to baseline"
              draw={(element) => drawAnchors(element, ensemble)}
              deps={[ensemble]}
            />
          </div>
          <DataTable
            id="ensemble-table"
            rows={rows}
            columns={ensembleColumns}
            maxHeight={300}
            onRow={(run) =>
              updateQuery({
                comparison: run.id,
                alignment: run.alignment,
                alignmentApplied: false,
                shift: 0,
                alignmentScale: 1,
              })
            }
          />
        </>
      )}
    </Card>
  );
}
