import { useLayoutEffect, useState } from "react";
import { Card } from "../../components/panel/Card";
import { ControlBar } from "../../components/controls/ControlBar";
import { getState, updateState } from "../../state/store";
import { useStore } from "../../state/useStore";
import { notify } from "../../state/uiActions";
import { updateQuery } from "../shared/dataControls";
import {
  buttonControl as button,
  numberControl as number,
  selectControl as select,
} from "../../components/controls/factories";
import { useComparisonActions } from "./useComparisonActions";
import { EnsemblePanel } from "./EnsemblePanel";
import type { ComparisonProps } from "./types";

const RESET = { shift: 0, alignmentScale: 1, alignmentApplied: false };

export function CrossRunPanel({ data, snapshot }: ComparisonProps) {
  const { archives, queryError } = data;
  const [anchor, setAnchor] = useState(() => snapshot.alignmentAnchor || "");
  const actions = useComparisonActions();
  const ensemble = snapshot.ensemble?.baseline.id === snapshot.id ? snapshot.ensemble : null;
  const { id, name, comparison, constraints } = useStore((state) => ({
    id: state.id,
    name: state.meta?.name || "",
    comparison: state.comparison || "",
    constraints: state.runAlignmentConstraints[state.comparison || ""] || "",
  }));
  const [shift, setShift] = useState(() => String(getState().shift || 0));
  const [scale, setScale] = useState(() => String(getState().alignmentScale || 1));
  useLayoutEffect(() => {
    setAnchor(snapshot.alignmentAnchor || "");
  }, [snapshot.alignmentAnchor]);
  useLayoutEffect(() => {
    setShift(String(snapshot.shift || 0));
    setScale(String(snapshot.alignmentScale || 1));
  }, [snapshot.shift, snapshot.alignmentScale]);
  const apply = () => {
    const shiftValue = Number(shift),
      factor = Number(scale);
    if (!Number.isFinite(shiftValue + factor) || factor <= 0)
      return notify("Enter a finite offset and positive time scale.");
    updateQuery({ shift: shiftValue, alignmentScale: factor, alignmentApplied: false });
  };
  return (
    <>
      <Card
        title="Cross-run comparison"
        caption={
          <span>
            {
              "Mapping: baseline time = offset + scale × comparison time. Profile costs retain physical seconds in each run. Baseline location filters apply to the baseline; comparison includes all its locations."
            }
          </span>
        }
      >
        <ControlBar
          controls={[
            {
              kind: "content",
              children: (
                <label>
                  Baseline <strong>{name}</strong>
                </label>
              ),
            },
            select(
              "comparison-trace",
              "Comparison",
              comparison,
              [
                ["", "Select another trace…"],
                ...archives
                  .filter((trace) => trace.id !== id)
                  .map((trace) => [trace.id, trace.name] as const),
              ],
              actions.select.mutate,
            ),
          ]}
        />
        <ControlBar
          controls={[
            {
              kind: "text",
              id: "alignment-anchor",
              label: "Anchor name contains",
              value: anchor,
              onChange: setAnchor,
              placeholder: "Automatic function / marker selection",
            },
            button(
              "find-alignment",
              actions.align.isPending ? "Matching recorded anchors…" : "Find automatic alignment",
              () => actions.align.mutate(anchor),
              {
                className: "primary",
                disabled:
                  actions.select.isPending ||
                  actions.align.isPending ||
                  !archives.some((trace) => trace.id === comparison && trace.loaded),
              },
            ),
          ]}
        />
        <details className="alignment-constraints">
          <summary>Explicit anchor pairs for the selected comparison</summary>
          <label>
            Baseline seconds, comparison seconds
            <textarea
              id="alignment-constraints"
              rows={3}
              spellCheck={false}
              placeholder={"0.5, 1.2\n4.0, 5.7"}
              value={constraints}
              onChange={(event) => {
                if (comparison)
                  updateState({
                    runAlignmentConstraints: {
                      ...getState().runAlignmentConstraints,
                      [comparison]: event.target.value,
                    },
                  });
              }}
            />
          </label>
          <p className="muted">
            {
              "One pair per line. Anchors must increase in both runs. These pairs resolve repeated phases and remain exact in piecewise mapping."
            }
          </p>
        </details>
        <ControlBar
          controls={[
            number("comparison-shift", "Offset", shift, setShift, { suffix: " s" }),
            number("comparison-scale", "Time scale", scale, setScale, { min: "0.000000001" }),
            button("compare-apply", "Apply manual mapping", apply),
            button("compare-reset", "Reset", () => updateQuery(RESET)),
          ]}
        />
        {queryError && <p className="analysis-warning">{queryError}</p>}
      </Card>
      <EnsemblePanel
        archives={archives}
        ensemble={ensemble}
        aligning={actions.alignMany.isPending}
        onAlign={() => actions.alignMany.mutate(anchor)}
      />
    </>
  );
}
