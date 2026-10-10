import { useCallback, useRef, useState } from "react";
import { hashKey } from "@tanstack/react-query";
import { queryClient } from "../../api/queryClient";
import { getState, updateState } from "../../state/store";
import { scheduleRender } from "../../state/viewActions";
import { notify } from "../../state/uiActions";
import type { TraceMeta } from "../../api/types/common";
import { captureProgram, createDraft, defaultProgram } from "./program";
import { startingPreset } from "./presets";
import { errorMessage } from "./requests";
import type { MetricDraft, MetricPreset, MetricProgram } from "./types";

export interface MetricEditorState {
  draft: MetricDraft;
  expression: string;
  field: (key: string, value: string) => void;
  source: (index: number, key: string, value: string) => void;
  capture: () => MetricProgram;
  commit: (change?: (program: MetricProgram) => MetricProgram) => void;
  add: () => void;
  remove: (index: number) => void;
  preset: (value: string, presets: readonly MetricPreset[]) => void;
}
export function useMetricEditor(
  program: MetricProgram,
  meta: TraceMeta,
  library: readonly string[],
): MetricEditorState {
  const form = useRef<MetricDraft>(null);
  if (!form.current) form.current = createDraft(program, meta, library);
  const draft = form.current;
  const [expression, setExpression] = useState(() => draft.program.expression);
  const capture = useCallback(() => {
    const next = captureProgram(form.current!);
    updateState({ metricProgram: next });
    return next;
  }, []);
  const commit = (change?: (program: MetricProgram) => MetricProgram) => {
    try {
      const next = capture();
      if (change) updateState({ metricProgram: change(next) });
      scheduleRender();
      if (!change && hashKey([next]) === hashKey([program]))
        void queryClient.invalidateQueries({ queryKey: ["view", "metrics"], type: "active" });
    } catch (error) {
      notify(errorMessage(error));
    }
  };
  // Unapplied controls keep their native drafts; only operation insertion updates visible text.
  const field = (key: string, value: string) => {
    draft.program[key] = value;
    if (key === "expression") setExpression(value);
  };
  const source = (index: number, key: string, value: string) => {
    const row = draft.sources[index]!;
    if (key === "variable" || key === "extra") row[key] = value;
    else row.fields[key] = value;
    if (key === "type") commit();
  };
  const add = () =>
    commit((next) => {
      const sources = { ...next.sources };
      let index = Object.keys(sources).length;
      while (Object.hasOwn(sources, `v${index}`)) index++;
      sources[`v${index}`] = { type: "constant", value: 1 };
      return { ...next, sources };
    });
  const remove = (index: number) =>
    commit((next) => ({
      ...next,
      sources: Object.fromEntries(Object.entries(next.sources).filter((_, i) => i !== index)),
    }));
  const preset = (value: string, presets: readonly MetricPreset[]) => {
    const trace = getState().meta;
    if (!trace) return;
    const native = value.startsWith("native:");
    const item = presets.find((preset) => preset.id === value.slice(7));
    if (native && !item?.available)
      return notify(item?.reason || "This preset is unavailable for the selected trace.");
    const selected =
      native && item
        ? { ...defaultProgram(trace), ...structuredClone(item.program) }
        : startingPreset(value, trace);
    if (selected) {
      updateState({ metricProgram: selected });
      scheduleRender();
    }
    if (native && item?.notes?.length) notify(item.notes.join(" "));
  };
  return { draft, expression, field, source, capture, commit, add, remove, preset };
}
