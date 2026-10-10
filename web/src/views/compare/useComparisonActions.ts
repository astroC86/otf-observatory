import { useMutation } from "@tanstack/react-query";
import { api, query, scope } from "../../api/client";
import type { ImportJob } from "../../api/types/common";
import { getState, updateState } from "../../state/store";
import { scheduleRender } from "../../state/viewActions";
import { notify } from "../../state/uiActions";
import { waitImport } from "../../state/trace/open";
import { updateQuery } from "../shared/dataControls";
import { openRuns } from "./requests";
import { readConstraints } from "./actions";
import type { Alignment, Ensemble } from "./types";

const onError = (error: Error) => notify(error.message);

export function useComparisonActions() {
  const select = useMutation({
    onError,
    mutationFn: async (comparison: string) => {
      updateState({
        comparison,
        alignment: null,
        alignmentApplied: false,
        shift: 0,
        alignmentScale: 1,
      });
      if (comparison) {
        const opened = await api<ImportJob>("open", {}, { id: comparison });
        if (opened.state !== "ready") {
          notify("Opening comparison trace…");
          await waitImport(comparison);
        }
      }
      scheduleRender();
    },
  });
  const align = useMutation({
    onError,
    mutationFn: async (anchor: string) => {
      updateState({ alignmentAnchor: anchor });
      const { id, comparison: other, runAlignmentConstraints: constraints } = getState();
      const data = await query<Alignment>("align", {
        other,
        anchor,
        constraints: JSON.stringify(readConstraints(constraints[other || ""] || "")),
      });
      if (getState().id !== id || getState().comparison !== other) return;
      updateQuery({
        alignment: data,
        alignmentMode: ["affine", "piecewise"].includes(data.recommendedMode)
          ? data.recommendedMode
          : "affine",
        alignmentApplied: false,
      });
    },
  });
  const alignMany = useMutation({
    onError,
    mutationFn: async (anchor: string) => {
      const { id, comparisonRuns: ids, runAlignmentConstraints: constraints } = getState();
      if (!ids.length || ids.length > 15) return notify("Select between 1 and 15 comparison runs.");
      const selection = scope();
      const runs = Object.fromEntries(
        ids.map((id) => [id, { constraints: readConstraints(constraints[id] || "") }]),
      );
      await openRuns(ids);
      const data = await api<Ensemble>(
        "align-many",
        {},
        { ...selection, id, baseline: id, ids: [id, ...ids], anchor, runs },
      );
      if (getState().id !== id || getState().comparisonRuns.join() !== ids.join()) return;
      updateQuery({ ensemble: data, ensembleApplied: false });
    },
  });
  return { select, align, alignMany };
}
