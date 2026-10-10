import type { ChangeEvent } from "react";
import { initialState, type AppState, type SavedSession } from "./types";
import { getState, updateState } from "./store";
import { views, setView } from "./viewActions";
import { locations } from "./selectors";
import { setRange } from "./rangeActions";
import { notify } from "./uiActions";
import { beginTraceLoad, isCurrentTraceLoad } from "./trace/requests";
import { openTrace } from "./trace/open";
import { download } from "../lib/download";

const transientKeys: Partial<Record<keyof AppState, true>> = {
  id: true,
  meta: true,
  start: true,
  end: true,
  locations: true,
  history: true,
  historyIndex: true,
  selectedRegion: true,
  collapsed: true,
  tableSearch: true,
};
// Existing fields retain their default insertion order; absent optional fields
// must be appended in this order when a session first introduces them.
const restoredKeys = (Object.keys(initialState) as (keyof AppState)[])
  .filter((key) => !transientKeys[key])
  .concat("metricLibrary", "dockLayout");

export function restoreState(saved: Partial<SavedSession>) {
  const meta = getState().meta;
  if (!meta) return;
  const patch: Partial<AppState> = {};
  const values = patch as Record<string, unknown>;
  for (const key of restoredKeys) {
    if (saved[key as keyof SavedSession] !== undefined)
      values[key] = saved[key as keyof SavedSession];
    else if (Object.hasOwn(initialState, key)) values[key] = structuredClone(initialState[key]);
  }
  if (!views.some((view) => view[0] === patch.view)) patch.view = "timeline";
  if (saved.locations) patch.locations = new Set(saved.locations.filter((id) => locations[id]));
  updateState(patch);
  setRange(saved.start ?? 0, saved.end ?? meta.duration);
  setView(getState().view);
}
export function sessionObject(): SavedSession {
  const { meta, locations: selected, history, historyIndex, collapsed, ...rest } = getState();
  return {
    ...rest,
    format: "otf-observatory-session",
    version: 1,
    path: meta?.path,
    locations: [...selected],
  };
}
export function saveSession() {
  if (!getState().meta) return notify("Open a trace first.");
  download("trace-session.json", JSON.stringify(sessionObject(), null, 2));
}
export async function restoreSession(event: ChangeEvent<HTMLInputElement>) {
  const request = beginTraceLoad();
  try {
    const file = event.target.files?.[0];
    if (!file) return;
    const value: unknown = JSON.parse(await file.text());
    if (
      !value ||
      typeof value !== "object" ||
      !("format" in value) ||
      value.format !== "otf-observatory-session"
    )
      throw Error("Not an Observatory session file");
    // Preserve the established session-file contract after its original format check.
    const saved = value as SavedSession;
    if (!isCurrentTraceLoad(request)) return;
    await openTrace({ path: saved.path }, saved, request);
  } catch (error) {
    notify(error instanceof Error ? error.message : String(error));
  }
}
