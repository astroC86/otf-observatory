import { create } from "zustand";
import { useShallow } from "zustand/react/shallow";
import { getState, updateState } from "../state/store";
import { notify } from "../state/uiActions";
import * as model from "./layout";
import type {
  DockLayout,
  DockPosition,
  DragDisplay,
  FrameSource,
  PanelChoice,
  Rect,
  WorkspaceBounds,
} from "./types";

export const emptyLayout: DockLayout = {
  version: 1,
  root: null,
  floats: [],
  panels: {},
  name: "Custom workspace",
};
export const idleDrag: DragDisplay = {
  interacting: false,
  label: "",
  left: 0,
  top: 0,
  preview: null,
};
const initial = {
  layout: emptyLayout,
  initialized: false,
  focused: "",
  maximized: "",
  active: false,
  expanded: false,
  pickedChart: "single-master",
  pickedPosition: "center" as DockPosition,
  announcement: "",
  frames: [] as FrameSource[],
  poolOrder: [] as string[],
  restoreVersion: 0,
  bounds: { left: 0, top: 0, width: 0, height: 0, clipPath: "" } as WorkspaceBounds,
  drag: idleDrag,
  dialog: "" as "" | "saved" | "arrange",
  target: "",
};
type WorkspaceState = typeof initial;
export const workspaceStore = create(() => initial);
export const getWorkspace = workspaceStore.getState;
export function useWorkspace<T>(selector: (state: WorkspaceState) => T): T {
  return workspaceStore(useShallow(selector));
}
let timer = 0;
export function stopSaving() {
  clearTimeout(timer);
}
export function persistLayout() {
  try {
    localStorage.setItem(model.STORAGE, JSON.stringify(getWorkspace().layout));
  } catch {
    notify("Browser storage is full. Export the layout to keep it.");
  }
}
export function saveLayout() {
  updateState({ dockLayout: getWorkspace().layout });
  clearTimeout(timer);
  timer = window.setTimeout(persistLayout, 220);
}
export function updateWorkspace(patch: Partial<WorkspaceState>) {
  const state = { ...getWorkspace(), ...patch };
  const frames = state.frames.filter((frame) => state.layout.panels[frame.id]);
  const groups = model.groups(state.layout);
  const geometry = model.workspaceGeometry(state.layout, state.bounds, state.maximized);
  for (const group of groups) {
    const rect = geometry.rects.get(group.id);
    if (!state.active || !rect || rect.h <= model.HEADER || rect.w < 10) continue;
    const panel = state.layout.panels[group.active];
    if (!panel) continue;
    const index = frames.findIndex((frame) => frame.id === panel.id);
    const previous = frames[index];
    if (previous?.view === panel.view && previous.chart === panel.chart) continue;
    const url = `${location.origin}${location.pathname}?embed=1&panel=${panel.id}${panel.chart ? "&chart=" + panel.chart : ""}#${panel.view}`;
    const frame = { id: panel.id, view: panel.view, chart: panel.chart, url };
    if (index < 0) frames.push(frame);
    else frames[index] = frame;
  }
  const keys = [
    ...groups.map((group) => `pane:${group.id}`),
    ...frames.map((frame) => `frame:${frame.id}`),
    ...(state.active
      ? geometry.splits.map((split) => `split:${split.node.id}`)
      : state.poolOrder.filter((key) => key.startsWith("split:"))),
  ];
  const wanted = new Set(keys),
    previous = new Set(state.poolOrder);
  // Keep surviving nodes in append order: moving an iframe resets its document.
  const poolOrder = [
    ...state.poolOrder.filter((key) => wanted.has(key)),
    ...keys.filter((key) => !previous.has(key)),
  ];
  workspaceStore.setState({ ...patch, frames, poolOrder });
}
export function editWorkspace(change: (draft: WorkspaceState) => void, save = true) {
  const state = { ...getWorkspace(), layout: model.draftLayout(getWorkspace().layout) };
  change(state);
  model.pruneLayout(state.layout);
  const live = model.groups(state.layout);
  if (!live.some((group) => group.id === state.focused)) state.focused = live[0]?.id || "";
  if (!live.some((group) => group.id === state.maximized)) state.maximized = "";
  updateWorkspace(state);
  if (save) saveLayout();
}
export function activate(groupId: string, panelId: string) {
  editWorkspace((state) => {
    const group = model.groups(state.layout).find((entry) => entry.id === groupId);
    if (!group?.tabs.includes(panelId)) return;
    group.active = panelId;
    state.focused = groupId;
    const floating = state.layout.floats.find((entry) => entry.group.id === groupId);
    if (floating) floating.z = Math.max(0, ...state.layout.floats.map((entry) => entry.z)) + 1;
  });
}
export function dockIds(
  ids: string[],
  target: string | null,
  position: DockPosition = "center",
  rect?: Rect,
) {
  editWorkspace((state) => {
    ids = ids.filter((id) => state.layout.panels[id]);
    if (!ids.length) return;
    const before = model.groups(state.layout).find((group) => group.id === target);
    if (
      position !== "float" &&
      before?.tabs.includes(ids[0]!) &&
      before.tabs.every((id) => ids.includes(id))
    )
      return;
    state.maximized = "";
    state.focused = model.placePanels(
      state.layout,
      ids,
      target,
      position,
      rect,
      state.bounds.width,
    );
    state.announcement = `${ids.length === 1 ? model.panelTitle(state.layout.panels[ids[0]!]!) : "Chart group"} ${position === "float" ? "floating" : "docked"}.`;
  });
}
const comparisonKeys = [
  "comparison",
  "shift",
  "alignment",
  "alignmentApplied",
  "alignmentAnchor",
  "alignmentScale",
  "alignmentMode",
  "alignmentConstraints",
  "runAlignmentConstraints",
  "comparisonRuns",
  "ensemble",
  "ensembleMode",
  "ensembleApplied",
  "markerInputs",
  "markerSession",
  "markerWindow",
  "markerSelectedLocationOnly",
] as const;
export function addPanel(
  value: string | PanelChoice = "timeline",
  position: DockPosition = "center",
  target: string | null = getWorkspace().focused,
) {
  const resolved = model.choice(value);
  if (!model.knownViews().some(([id]) => id === resolved.view)) return null;
  if (Object.keys(getWorkspace().layout.panels).length >= model.MAX_PANELS) {
    notify(`Close a chart before adding more than ${model.MAX_PANELS}.`);
    return null;
  }
  if (!model.validChart(resolved.view, resolved.chart)) delete resolved.chart;
  const id = model.uid("panel"),
    state = getState();
  const settings =
    resolved.view === "compare"
      ? Object.fromEntries(
          comparisonKeys
            .filter((key) => state[key] !== undefined)
            .map((key) => [key, model.copy(state[key])]),
        )
      : {};
  updateWorkspace({
    layout: {
      ...getWorkspace().layout,
      panels: { ...getWorkspace().layout.panels, [id]: { id, ...resolved, settings } },
    },
  });
  dockIds([id], target, position);
  return id;
}
export function closePanel(id: string) {
  editWorkspace((state) => {
    const panel = state.layout.panels[id];
    if (!panel) return;
    model.removeTabs(state.layout, [id]);
    delete state.layout.panels[id];
    state.announcement = `${model.panelTitle(panel)} closed.`;
  });
}
export function loadLayout(raw: unknown) {
  const layout = model.normalize(raw);
  updateWorkspace({
    layout,
    focused: model.groups(layout)[0]?.id || "",
    maximized: "",
    restoreVersion: getWorkspace().restoreVersion + 1,
    announcement: "Layout restored.",
  });
  saveLayout();
}
export function setPreset(name: string) {
  const layout = model.makePreset(name, getWorkspace().layout);
  updateWorkspace({
    layout,
    focused: model.groups(layout)[0]?.id || "",
    maximized: "",
    announcement: `${name} layout applied.`,
  });
  saveLayout();
}
