import { createStore } from "zustand/vanilla";
import {
  initialState,
  initialUi,
  type AppState,
  type StatePatch,
  type UiState,
  type ViewState,
} from "./types";
import type { MarkerInput } from "../views/compare/types";

export interface ClientStore {
  state: Readonly<AppState>;
  ui: Readonly<UiState>;
  committed: ViewState | null;
  updateState: (patch: StatePatch) => void;
  updateUi: (patch: Partial<UiState>) => void;
  commitView: () => void;
}
function changed<T extends object>(previous: T, patch: Partial<T>): boolean {
  for (const key of Object.keys(patch) as (keyof T)[]) {
    if (!Object.hasOwn(previous, key) || !Object.is(previous[key], patch[key])) return true;
  }
  return false;
}
export const appStore = createStore<ClientStore>()((set, get) => ({
  state: initialState,
  ui: initialUi,
  committed: null,
  updateState: (patch) =>
    set((store) => {
      const next = typeof patch === "function" ? patch(store.state) : patch;
      return changed(store.state, next)
        ? { state: Object.freeze({ ...store.state, ...next }) }
        : store;
    }),
  updateUi: (patch) =>
    set((store) =>
      changed(store.ui, patch) ? { ui: Object.freeze({ ...store.ui, ...patch }) } : store,
    ),
  commitView: () => {
    const store = get(),
      { ui } = store;
    let state = store.state;
    const meta = state.meta;
    if (!meta) return;
    // Comparing appends marker defaults even when the query result is cached.
    if (state.view === "compare" && state.id !== null) {
      let markerInputs: Record<string, MarkerInput> | undefined;
      for (const id of [state.id, ...state.comparisonRuns]) {
        if ((markerInputs ?? state.markerInputs)[id]) continue;
        markerInputs ??= { ...state.markerInputs };
        markerInputs[id] = { time: 0, offset: 0 };
      }
      if (markerInputs)
        state = Object.freeze({ ...state, markerInputs: Object.freeze(markerInputs) });
    }
    const epoch = ui.epoch + 1;
    set({
      state,
      committed: Object.freeze({ ...state, meta, epoch }),
      ui: Object.freeze({
        ...ui,
        epoch,
        busy: true,
        status: "Querying selection…",
        statusIcon: true,
      }),
    });
  },
}));
export const getState = (): Readonly<AppState> => appStore.getState().state;
export const getUi = (): Readonly<UiState> => appStore.getState().ui;
export const getViewState = (): ViewState | null => appStore.getState().committed;
export const { updateState, updateUi, commitView } = appStore.getState();
