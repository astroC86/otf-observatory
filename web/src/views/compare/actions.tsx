import { getState, updateState, updateUi } from "../../state/store";
import { notify } from "../../state/uiActions";
import { inspectObject } from "../../state/inspection";
import { updateQuery } from "../shared/dataControls";
import type { AppState } from "../../state/types";
import type { AnchorPair, MarkerInput, TimeRange } from "./types";

const LINES = /\n/;
const SEPARATOR = /[,\s]+/;
export const EMPTY_MARKER_INPUT: MarkerInput = { time: 0, offset: 0 };

export function readConstraints(text: string): AnchorPair[] {
  return text.split(LINES).flatMap((line, index) => {
    line = line.trim();
    if (!line || line.startsWith("#")) return [];
    const [a, b, extra] = line.split(SEPARATOR);
    if (extra !== undefined || [a, b].some((value) => !Number.isFinite(Number(value)))) {
      throw Error(`Anchor line ${index + 1}: enter baseline seconds, comparison seconds.`);
    }
    return [{ timeA: Number(a), timeB: Number(b), label: `Explicit anchor ${index + 1}` }];
  });
}

export function inspectEvidence(row: object) {
  inspectObject(
    ("label" in row && row.label) || ("kind" in row && row.kind) || "Analysis evidence",
    row,
  );
}

export function inspectAnchor(row: AnchorPair) {
  const add = () => {
    const { comparison, runAlignmentConstraints: constraints } = getState();
    const id = comparison || "";
    const pairs = readConstraints(constraints[id] || "");
    if (!pairs.some((pair) => pair.timeA === row.timeA && pair.timeB === row.timeB))
      pairs.push(row);
    const text = pairs
      .toSorted((a, b) => a.timeA - b.timeA)
      .map((pair) => `${pair.timeA}, ${pair.timeB}`)
      .join("\n");
    updateQuery({ runAlignmentConstraints: { ...constraints, [id]: text } });
    updateUi({ contextVisible: false });
    notify("Anchor pair added. Find alignment again to use it.");
  };
  inspectObject(row.label || ("kind" in row && row.kind) || "Analysis evidence", row, {
    after: (
      <button id="use-alignment-anchor" onClick={add}>
        Use this anchor pair
      </button>
    ),
  });
}

export function markerIds(state: Readonly<AppState>) {
  return [state.id || "", ...state.comparisonRuns];
}

export function captureMarkerInputs() {
  const state = getState(),
    markerInputs = { ...state.markerInputs };
  for (const id of markerIds(state)) {
    const input = markerInputs[id] || EMPTY_MARKER_INPUT;
    markerInputs[id] = { ...input, time: String(input.time), offset: String(input.offset) };
  }
  updateState({ markerInputs });
}

export function setMarkerInput(id: string, input: MarkerInput) {
  updateState({ markerInputs: { ...getState().markerInputs, [id]: input } });
}

export function setMarkerWindow(start: number, end: number) {
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    return notify("Enter an increasing, finite display-time range.");
  }
  updateQuery({ markerWindow: { start, end } });
}

export function preserveMarkerWindow(range: TimeRange): TimeRange {
  const { markerSession: session, markerWindow: view } = getState();
  const old = session?.range;
  if (!old || !view || (view.start === old.start && view.end === old.end)) return range;
  const width = Math.min(view.end - view.start, range.end - range.start);
  const start = Math.max(range.start, Math.min(view.start, range.end - width));
  return { start, end: start + width };
}
