import { getState, updateState, updateUi } from "./store";
import { render, scheduleRender } from "./viewActions";
import { duration } from "../lib/format/time";

export function setRange(start: number, end: number, history = true) {
  const state = getState();
  if (!state.meta) return;
  const max = state.meta.duration;
  const width = Math.min(max, Math.max(1e-9, end - start));
  start = Math.max(0, Math.min(start, max - width));
  end = start + width;
  const ranges = history
    ? state.history.toSpliced(state.historyIndex + 1, state.history.length, [start, end])
    : state.history;
  updateState({
    start,
    end,
    history: ranges,
    historyIndex: history ? ranges.length - 1 : state.historyIndex,
  });
  updateUi({
    rangeStart: String(Number(start.toPrecision(10))),
    rangeEnd: String(Number(end.toPrecision(10))),
    selection: `${duration(end - start)} selected · ${state.locations.size} locations`,
  });
  scheduleRender();
  window.dispatchEvent(new CustomEvent("otf-selection-changed"));
}
export function moveHistory(step: number) {
  const state = getState(),
    index = state.historyIndex + step;
  const range = state.history[index];
  if (!range) return;
  updateState({ historyIndex: index });
  setRange(range[0], range[1], false);
  render();
}
export function zoom(factor: number) {
  const state = getState(),
    mid = (state.start + state.end) / 2;
  const width = (state.end - state.start) * factor;
  setRange(mid - width / 2, mid + width / 2);
}
