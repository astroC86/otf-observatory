import { useEffect, useLayoutEffect, type RefObject } from "react";
import { appStore, getState, updateState } from "../state/store";
import { useUi } from "../state/useUi";
import { setRange } from "../state/rangeActions";
import { notify } from "../state/uiActions";
import { finishRender } from "../state/viewActions";
import * as model from "./layout";
import {
  addPanel,
  closePanel,
  dockIds,
  editWorkspace,
  emptyLayout,
  getWorkspace,
  loadLayout,
  persistLayout,
  saveLayout,
  setPreset,
  stopSaving,
  updateWorkspace,
  workspaceStore,
} from "./store";
import type { DockingApi } from "./types";

type Frame = {
  element: HTMLIFrameElement;
  ready: boolean;
  version: number;
  last: string;
  url: string;
};
const frames = new Map<string, Frame>();
let originPanel: string | null = null;
export function registerFrame(element: HTMLIFrameElement | null) {
  const id = element?.dataset.panelId;
  if (!element || !id) return;
  frames.set(id, { element, ready: false, version: -1, last: "", url: element.src });
  return () => {
    frames.delete(id);
  };
}
function broadcast(force = "") {
  const workspace = getWorkspace(),
    state = getState();
  if (!workspace.active || !state.id) return;
  const geometry = model.workspaceGeometry(workspace.layout, workspace.bounds, workspace.maximized);
  for (const group of model.groups(workspace.layout)) {
    const id = group.active,
      frame = frames.get(id),
      rect = geometry.rects.get(group.id);
    if (frame && frame.url !== frame.element.src) frame.ready = false;
    if (!frame?.ready || !rect || rect.h <= model.HEADER || rect.w < 10) continue;
    const payload = {
      type: "otf-dock-state",
      panelId: id,
      traceId: state.id,
      start: state.start,
      end: state.end,
      locations: [...state.locations],
      region: state.region || "",
      exclude: state.exclude || "",
      group: state.group || "",
      originPanel,
    };
    const signature = JSON.stringify({ ...payload, originPanel: null });
    const initialize = frame.version !== workspace.restoreVersion;
    if (id !== force && frame.last === signature && !initialize) continue;
    frame.element.contentWindow?.postMessage(
      {
        ...payload,
        ...(initialize
          ? {
              initialize: true,
              settings: model.sanitizeSettings(workspace.layout.panels[id]!.settings),
            }
          : {}),
      },
      location.origin,
    );
    frame.last = signature;
    frame.version = workspace.restoreVersion;
  }
}
function message(event: MessageEvent<unknown>) {
  if (event.origin !== location.origin) return;
  const found = [...frames].find(([, frame]) => frame.element.contentWindow === event.source);
  if (!found) return;
  const [id, frame] = found,
    data = model.record(event.data),
    workspace = getWorkspace();
  const panel = workspace.layout.panels[id];
  if (!panel) return;
  if (data.type === "otf-dock-ready") {
    frame.url = frame.element.src;
    frame.ready = true;
    frame.version = -1;
    broadcast(id);
  } else if (data.type === "otf-dock-error") {
    notify(
      `${model.panelTitle(panel)}: ${String(data.message || "Unable to load chart").slice(0, 500)}`,
    );
  } else if (
    data.type === "otf-dock-panel-state" &&
    data.settings &&
    typeof data.settings === "object"
  ) {
    const settings = model.record(data.settings);
    editWorkspace((draft) => {
      const updated = { ...panel, settings: model.sanitizeSettings(settings) };
      if (
        typeof settings.view === "string" &&
        model.knownViews().some(([view]) => view === settings.view)
      )
        updated.view = settings.view;
      if (!model.validChart(updated.view, updated.chart)) delete updated.chart;
      draft.layout.panels[id] = updated;
      draft.frames = draft.frames.map((source) =>
        source.id === id ? { ...source, view: updated.view, chart: updated.chart } : source,
      );
    });
  } else if (data.type === "otf-dock-selection" && workspace.active && !frame.element.hidden) {
    const state = getState(),
      max = Number(state.meta?.duration);
    const start = Number(data.start),
      end = Number(data.end);
    if (
      (data.traceId && data.traceId !== state.id) ||
      !Number.isFinite(start) ||
      !Number.isFinite(end) ||
      start < 0 ||
      end < start ||
      !Number.isFinite(max)
    )
      return;
    const valid = new Set(state.meta?.locations.map((location) => String(location.id)));
    const locations = Array.isArray(data.locations)
      ? data.locations.map(String).filter((id) => valid.has(id))
      : [...state.locations];
    const selection = {
      start: model.clamp(start, 0, max),
      end: model.clamp(end, 0, max),
      region: typeof data.region === "string" ? data.region.slice(0, 10000) : state.region,
      exclude: typeof data.exclude === "string" ? data.exclude.slice(0, 10000) : state.exclude,
      group: typeof data.group === "string" ? data.group.slice(0, 1000) : state.group,
    };
    if (
      Object.entries(selection).every(
        ([key, value]) => state[key as keyof typeof selection] === value,
      ) &&
      locations.length === state.locations.size &&
      locations.every((id) => state.locations.has(id))
    )
      return;
    originPanel = id;
    updateState({
      locations: new Set(locations),
      region: selection.region,
      exclude: selection.exclude,
      group: selection.group,
    });
    setRange(selection.start, selection.end);
    broadcast();
    originPanel = null;
  }
}
const api: DockingApi = {
  getLayout: () => model.copy(getWorkspace().layout),
  addPanel,
  dockPanel: (id, target, position) => dockIds([id], target, position),
  floatPanel: (id) => dockIds([id], null, "float"),
  closePanel,
  setPreset,
  saveLayout,
  loadLayout,
  broadcast,
};
export function useDockRuntime(
  stage: RefObject<HTMLDivElement | null>,
  active: boolean,
  expanded: boolean,
  epoch: number,
) {
  const enabled = useUi((ui) => ui.initialized && !ui.embedded);
  useEffect(() => {
    if (!enabled) return;
    if (!getWorkspace().initialized) {
      let layout;
      try {
        layout = model.normalize(
          getState().dockLayout || JSON.parse(localStorage.getItem(model.STORAGE) || "null"),
        );
      } catch {
        layout = model.makePreset("Analysis", emptyLayout);
      }
      updateWorkspace({ layout, focused: model.groups(layout)[0]?.id || "", initialized: true });
      updateState({ dockLayout: layout });
    }
    window.otfDocking = api;
    let external = getState().dockLayout,
      frame = 0;
    const unsubscribe = appStore.subscribe(() => {
      const next = getState().dockLayout;
      if (external === next) return;
      external = next;
      if (!next || next === getWorkspace().layout) return;
      try {
        loadLayout(next);
      } catch (error) {
        notify(error instanceof Error ? error.message : String(error));
        updateState({ dockLayout: getWorkspace().layout });
      }
    });
    const changed = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => broadcast());
    };
    const unsubscribeWorkspace = workspaceStore.subscribe(changed);
    window.addEventListener("message", message);
    window.addEventListener("otf-selection-changed", changed);
    window.addEventListener("beforeunload", persistLayout);
    return () => {
      cancelAnimationFrame(frame);
      unsubscribe();
      unsubscribeWorkspace();
      window.removeEventListener("message", message);
      window.removeEventListener("otf-selection-changed", changed);
      window.removeEventListener("beforeunload", persistLayout);
      delete window.otfDocking;
      stopSaving();
    };
  }, [enabled]);
  useLayoutEffect(() => {
    const element = stage.current;
    // Other views unmount the stage; the docked pool must hide with it, as in vanilla.
    if (!element) {
      updateWorkspace({ active: false });
      return;
    }
    let frame = 0;
    const measure = () => {
      frame = 0;
      const visible = active && !document.hidden,
        box = element.getBoundingClientRect();
      updateWorkspace({
        active: visible,
        ...(visible
          ? {
              bounds: {
                left: box.left,
                top: box.top,
                width: Math.max(1, box.width),
                height: Math.max(1, box.height),
                clipPath: `inset(${Math.max(0, box.top)}px ${Math.max(0, document.documentElement.clientWidth - box.right)}px ${Math.max(0, document.documentElement.clientHeight - box.bottom)}px ${Math.max(0, box.left)}px)`,
              },
            }
          : {}),
      });
    };
    const queue = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    measure();
    const observer = new ResizeObserver(queue);
    observer.observe(element);
    window.addEventListener("resize", queue);
    window.addEventListener("scroll", queue, true);
    document.addEventListener("visibilitychange", queue);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", queue);
      window.removeEventListener("scroll", queue, true);
      document.removeEventListener("visibilitychange", queue);
    };
  }, [active, expanded]);
  useEffect(() => {
    if (enabled && active && epoch) finishRender(epoch, performance.now());
  }, [enabled, active, epoch]);
}
