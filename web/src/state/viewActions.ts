import { startTransition } from "react";
import { getState, getUi, updateState, updateUi, commitView } from "./store";
import { num } from "../lib/format/numbers";
import { duration } from "../lib/format/time";

export const views: readonly (readonly [string, string, string])[] = [
  ["workspace", "Workspace", "Dockable chart workspace"],
  ["timeline", "Timeline", "Execution timeline"],
  ["functions", "Functions", "Function summary"],
  ["calltree", "Call tree", "Calling context"],
  ["processes", "Processes", "Process summary"],
  ["counters", "Counters", "Counter data timeline"],
  ["metrics", "Metric studio", "Custom metrics & reductions"],
  ["waits", "Wait analysis", "Wait states & dependency delays"],
  ["dependencies", "Dependencies", "Locks, threads & tasks"],
  ["gpu", "GPU", "GPU kernels, memory & host correlation"],
  ["radar", "Radar", "Performance radar"],
  ["communication", "Communication", "MPI communication"],
  ["collectives", "Collectives", "Collective operations"],
  ["io", "I/O & RMA", "Shared resources"],
  ["system", "System", "System topology"],
  ["events", "Events", "Event browser"],
  ["markers", "Markers", "Markers & bookmarks"],
  ["compare", "Compare", "Trace comparison"],
  ["trace", "Trace", "Trace properties"],
];
let renderTimer = 0;
interface Work {
  pending: number;
  ready?: { started: number; error?: unknown };
}
const work = new Map<number, Work>();
export const active = (epoch: number) => !renderTimer && epoch === getUi().epoch;
export function scheduleRender() {
  clearTimeout(renderTimer);
  renderTimer = window.setTimeout(render, 120);
  if (getState().meta) updateUi({ busy: true, status: "Querying selection…", statusIcon: true });
}
export function render() {
  clearTimeout(renderTimer);
  renderTimer = 0;
  if (!getState().meta) return;
  work.clear();
  startTransition(commitView);
}
export function setView(name: string) {
  if (!views.some((view) => view[0] === name)) return;
  updateState({ view: name });
  location.hash = name;
  scheduleRender();
}
function flushRender(epoch: number) {
  const current = work.get(epoch);
  if (!active(epoch) || !current?.ready || current.pending) return;
  const state = getState(),
    { started, error } = current.ready;
  work.delete(epoch);
  updateUi({
    busy: false,
    status: error ? "Query failed" : `${num(state.meta?.counts.events, 0)} events indexed`,
    statusIcon: !error,
    ...(error
      ? {}
      : {
          queryTime: `${num(performance.now() - started, 0)} ms`,
          selection: `${duration(state.end - state.start)} selected · ${state.locations.size} locations`,
        }),
  });
  if (!error) window.dispatchEvent(new CustomEvent("otf-selection-changed"));
}
export function beginViewWork(epoch: number): () => void {
  const current = work.get(epoch) || { pending: 0 };
  current.pending++;
  work.set(epoch, current);
  let ended = false;
  return () => {
    if (ended) return;
    ended = true;
    const pending = work.get(epoch);
    if (pending) {
      pending.pending--;
      flushRender(epoch);
    }
  };
}
export function finishRender(epoch: number, started: number, error?: unknown) {
  if (!active(epoch)) return;
  const current = work.get(epoch) || { pending: 0 };
  current.ready = { started, error };
  work.set(epoch, current);
  flushRender(epoch);
}
