import { getState, updateState } from "./store";
import { setRange } from "./rangeActions";
import { scheduleRender } from "./viewActions";
import { persistState } from "./persistence";

export type FilterKey = "region" | "exclude" | "group";
export function setFilter(key: FilterKey, value: string): void {
  updateState({ [key]: value });
  scheduleRender();
}
export function clearFilters(): void {
  updateState({ region: "", exclude: "", group: "" });
  scheduleRender();
}
export function selectLocations(ids: Iterable<string>): void {
  updateState({ locations: new Set(ids) });
  const { start, end } = getState();
  setRange(start, end, false);
}
export function setLocationSelected(id: string, selected: boolean): void {
  const state = getState();
  if (state.locations.has(id) === selected) return;
  const locations = new Set(state.locations);
  if (selected) locations.add(id);
  else locations.delete(id);
  updateState({ locations });
  setRange(state.start, state.end, false);
}
export function setGroupColor(group: string, color: string): void {
  updateState((previous) => ({
    colors: { ...previous.colors, [group]: color },
  }));
  persistState("colors");
}
