import { scheduleRender } from "../state/viewActions";
import { updateState } from "../state/store";
import type { AppState, ViewState } from "../state/types";

export function change(
  patch: Partial<AppState> | ((previous: Readonly<AppState>) => Partial<AppState>),
) {
  updateState(patch);
  scheduleRender();
}

export function executionLocations(state: ViewState): string[] {
  return state.meta.locations
    .filter((location) => state.locations.has(location.id) && location.type !== "METRIC")
    .map((location) => location.id);
}
