import type { CSSProperties } from "react";
import { views } from "../state/viewActions";
import type * as T from "./types";

export const STORAGE = "otf-dock-layout-v1";
export const SAVED = "otf-dock-saved-v1";
export const MAX_PANELS = 24;
export const HEADER = 36;
export const GAP = 7;
export const charts = [
  ["single-master", "Master timeline", "timeline", "timeline-chart"],
  ["single-profile", "Function profile", "timeline", "profile-chart"],
  ["single-matrix", "Communication matrix", "communication", "matrix-chart"],
  ["single-transfer-summary", "Transfer summary", "communication", "transfer-summary-chart"],
  ["single-transfer-matrix", "Transfer matrix", "communication", "transfer-matrix-chart"],
  ["single-transfer-timeline", "Transfer timeline", "communication", "transfer-timeline-chart"],
  ["single-counter", "Counter timeline", "counters", "counter-chart"],
  ["single-radar", "Performance radar", "radar", "radar-chart"],
  ["single-dependencies", "Dependency timeline", "dependencies", "relationship-chart"],
  ["single-gpu", "GPU timeline", "gpu", "relationship-chart"],
  ["single-gpu-idle", "GPU idle statistics", "gpu", "gpu-idle-chart"],
  ["single-waits", "Wait timeline", "waits", "wait-chart"],
  ["single-marker-comparison", "Aligned comparison timelines", "compare", "marker-timeline"],
] as const;
export const knownViews = () => views.filter(([id]) => id !== "workspace");
export const validChart = (view: string, chart: unknown) =>
  charts.some((entry) => entry[2] === view && entry[3] === chart);
export const panelTitle = (panel: T.DockPanel) =>
  charts.find((entry) => entry[2] === panel.view && entry[3] === panel.chart)?.[1] ||
  views.find(([id]) => id === panel.view)?.[1] ||
  panel.view;
export function choice(value: string | T.PanelChoice): T.PanelChoice {
  if (value && typeof value === "object") return { view: value.view, chart: value.chart };
  const chart = charts.find(([id]) => id === value);
  return chart ? { view: chart[2], chart: chart[3] } : { view: value };
}
export const uid = (prefix: string) =>
  `${prefix}-${globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}`;
export const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(max, value));
export const copy = <V>(value: V): V => JSON.parse(JSON.stringify(value)) as V;
export function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
const excludedSettings = (
  "id meta path start end locations region exclude group view dockLayout " +
  "history historyIndex format version"
).split(" ");
export function sanitizeSettings(value: unknown): Record<string, unknown> {
  const result = copy(record(value));
  for (const key of excludedSettings) delete result[key];
  return result;
}
const idPattern = /^[\w-]{1,90}$/;
const finite = (value: unknown, fallback: number, min = 0, max = 10000) =>
  Number.isFinite(Number(value)) ? clamp(Number(value), min, max) : fallback;
export function normalize(value: unknown): T.DockLayout {
  const raw = record(value);
  if (raw.version !== 1) throw Error("Unsupported docking layout. Expected version 1.");
  const valid = new Set(knownViews().map(([id]) => id));
  const panels: T.DockLayout["panels"] = Object.create(null);
  const used = new Set<string>();
  const ids = new Set<string>();
  for (const [id, value] of Object.entries(record(raw.panels))) {
    if (Object.keys(panels).length >= MAX_PANELS)
      throw Error(`A workspace supports up to ${MAX_PANELS} charts.`);
    const panel = record(value);
    if (!idPattern.test(id) || ["__proto__", "constructor", "prototype"].includes(id)) continue;
    if (typeof panel.view !== "string" || !valid.has(panel.view)) continue;
    panels[id] = { id, view: panel.view, settings: sanitizeSettings(panel.settings) };
    if (validChart(panel.view, panel.chart)) panels[id].chart = String(panel.chart);
  }
  function uniqueId(value: unknown, prefix: string): string {
    const id =
      typeof value === "string" && idPattern.test(value) && !ids.has(value) ? value : uid(prefix);
    ids.add(id);
    return id;
  }
  function clean(value: unknown, depth = 0): T.DockNode | null {
    if (!value || depth > 16) return null;
    const node = record(value);
    if (node.type === "group") {
      const tabs = (Array.isArray(node.tabs) ? node.tabs : []).filter(
        (id): id is string =>
          typeof id === "string" && !!panels[id] && !used.has(id) && !!used.add(id),
      );
      if (!tabs.length) return null;
      const id = uniqueId(node.id, "group");
      const active =
        typeof node.active === "string" && tabs.includes(node.active) ? node.active : tabs[0]!;
      return { type: "group", id, tabs, active };
    }
    if (node.type !== "split") return null;
    const first = clean(node.first, depth + 1);
    const second = clean(node.second, depth + 1);
    if (!first || !second) return first || second;
    const id = uniqueId(node.id, "split");
    return split(
      node.axis === "y" ? "y" : "x",
      first,
      second,
      finite(node.ratio, 0.5, 0.1, 0.9),
      id,
    );
  }
  const root = clean(raw.root);
  const floats: T.DockFloat[] = [];
  for (const value of (Array.isArray(raw.floats) ? raw.floats : []).slice(0, MAX_PANELS)) {
    const floating = record(value);
    const group = clean(floating.group);
    if (group?.type !== "group") continue;
    floats.push({
      id: uniqueId(floating.id, "float"),
      group,
      x: finite(floating.x, 40),
      y: finite(floating.y, 40),
      w: finite(floating.w, 560, 220),
      h: finite(floating.h, 350, 150),
      z: finite(floating.z, floats.length, 0, 1000000),
    });
  }
  for (const id of Object.keys(panels)) if (!used.has(id)) delete panels[id];
  const name = typeof raw.name === "string" ? raw.name.slice(0, 100) : "Custom workspace";
  return { version: 1, root, floats, panels, name };
}
function split(
  axis: "x" | "y",
  first: T.DockNode,
  second: T.DockNode,
  ratio = 0.5,
  id = uid("split"),
): T.DockSplit {
  return { type: "split", id, axis, ratio, first, second };
}
export function newGroup(tabs: string[]): T.DockGroup {
  return { type: "group", id: uid("group"), tabs, active: tabs[0] || "" };
}
type Plan = string | ["x" | "y", Plan, Plan, number?];
const plans: Record<string, Plan> = {
  Analysis: [
    "y",
    "single-master",
    ["x", "single-profile calltree", "single-counter processes"],
    0.58,
  ],
  "GPU analysis": ["y", "gpu", ["x", "timeline", "counters waits"], 0.58],
  Communication: ["x", "timeline", ["y", "communication", "waits collectives"], 0.58],
  "Four charts": [
    "y",
    ["x", "single-master", "single-profile"],
    ["x", "single-counter", "single-matrix"],
  ],
  "Single chart": "single-master",
};
export const presets = Object.keys(plans);
export function makePreset(name: string, current: T.DockLayout): T.DockLayout {
  const reuse = new Map<string, T.DockPanel[]>();
  const panels: T.DockLayout["panels"] = Object.create(null);
  for (const panel of Object.values(current.panels)) {
    const key = `${panel.view}:${panel.chart || ""}`;
    const candidates = reuse.get(key) || [];
    candidates.push(panel);
    reuse.set(key, candidates);
  }
  function panel(value: string): string {
    const resolved = choice(value);
    const old = reuse.get(`${resolved.view}:${resolved.chart || ""}`)?.shift();
    const id = old?.id || uid("panel");
    panels[id] = old || { id, ...resolved, settings: {} };
    return id;
  }
  const build = (plan: Plan): T.DockNode =>
    typeof plan === "string"
      ? newGroup(
          plan
            .split(" ")
            .filter((value) => knownViews().some(([id]) => id === choice(value).view))
            .map(panel),
        )
      : split(plan[0], build(plan[1]), build(plan[2]), plan[3]);
  const root = build(Object.hasOwn(plans, name) ? plans[name]! : plans.Analysis!);
  return { version: 1, root, floats: [], panels, name };
}
export function allGroups(node: T.DockNode | null, result: T.DockGroup[] = []): T.DockGroup[] {
  if (node?.type === "group") result.push(node);
  if (node?.type === "split") {
    allGroups(node.first, result);
    allGroups(node.second, result);
  }
  return result;
}
export const groups = (layout: T.DockLayout) => [
  ...allGroups(layout.root),
  ...layout.floats.map((floating) => floating.group),
];
export function draftLayout(layout: T.DockLayout): T.DockLayout {
  return {
    ...layout,
    root: structuredClone(layout.root),
    floats: structuredClone(layout.floats),
    panels: { ...layout.panels },
  };
}
function prune(node: T.DockNode | null): T.DockNode | null {
  if (!node) return null;
  if (node.type === "group") {
    if (!node.tabs.length) return null;
    if (!node.tabs.includes(node.active)) node.active = node.tabs[0]!;
    return node;
  }
  const first = prune(node.first);
  const second = prune(node.second);
  if (!first || !second) return first || second;
  node.first = first;
  node.second = second;
  return node;
}
export function pruneLayout(layout: T.DockLayout): void {
  layout.root = prune(layout.root);
  layout.floats = layout.floats.filter((floating) => prune(floating.group));
}
export function replaceNode(node: T.DockNode | null, id: string, replacement: T.DockNode) {
  if (!node || node.id === id) return node ? replacement : null;
  if (node.type === "split") {
    node.first = replaceNode(node.first, id, replacement)!;
    node.second = replaceNode(node.second, id, replacement)!;
  }
  return node;
}
export function removeTabs(layout: T.DockLayout, ids: string[]): void {
  const removed = new Set(ids);
  for (const group of groups(layout)) {
    group.tabs = group.tabs.filter((id) => !removed.has(id));
    if (!group.tabs.includes(group.active)) group.active = group.tabs[0] || "";
  }
  pruneLayout(layout);
}
export function findNode(node: T.DockNode | null, id: string): T.DockNode | null {
  if (!node || node.id === id) return node;
  return node.type === "split" ? findNode(node.first, id) || findNode(node.second, id) : null;
}
export function placePanels(
  layout: T.DockLayout,
  ids: string[],
  targetId: string | null,
  position: T.DockPosition,
  point?: T.Rect,
  stageWidth = 650,
): string {
  removeTabs(layout, ids);
  const target = groups(layout).find((group) => group.id === targetId);
  if (position === "float") {
    const group = newGroup(ids);
    const { x, y, w, h } = point || { x: 45, y: 45, w: Math.min(650, stageWidth || 650), h: 380 };
    layout.floats.push({
      id: uid("float"),
      group,
      x,
      y,
      w: w || 560,
      h: h || 360,
      z: Math.max(0, ...layout.floats.map((floating) => floating.z)) + 1,
    });
    return group.id;
  }
  if (target && position === "center") {
    target.tabs.push(...ids);
    target.active = ids[0]!;
    return target.id;
  }
  const group = newGroup(ids);
  const axis = target
    ? position === "left" || position === "right"
      ? "x"
      : "y"
    : position === "top" || position === "bottom"
      ? "y"
      : "x";
  if (!target) layout.root = layout.root ? split(axis, layout.root, group) : group;
  else {
    const before = position === "left" || position === "top";
    const node = split(axis, before ? group : target, before ? target : group);
    const floating = layout.floats.find((entry) => entry.group.id === target.id);
    if (floating) {
      layout.floats = layout.floats.filter((entry) => entry !== floating);
      layout.root = layout.root ? split("x", layout.root, node, 0.65) : node;
    } else layout.root = replaceNode(layout.root, target.id, node);
  }
  return group.id;
}
export function workspaceGeometry(
  layout: T.DockLayout,
  bounds: T.WorkspaceBounds,
  maximized: string,
): T.WorkspaceGeometry {
  const rects = new Map<string, T.PaneRect>();
  const splits: T.SplitGeometry[] = [];
  const stage = { x: 0, y: 0, w: Math.max(1, bounds.width), h: Math.max(1, bounds.height) };
  function walk(node: T.DockNode | null, rect: T.Rect): void {
    if (!node) return;
    if (node.type === "group") rects.set(node.id, { ...rect, z: 2 });
    else {
      const axis = node.axis;
      const size = axis === "x" ? "w" : "h";
      const available = Math.max(0, rect[size] - GAP);
      const at = available * node.ratio;
      const divider = { ...rect, [axis]: rect[axis] + at, [size]: GAP };
      const second = { ...rect, [axis]: rect[axis] + (at + GAP), [size]: available - at };
      splits.push({ node, rect: divider, parent: rect });
      walk(node.first, { ...rect, [size]: at });
      walk(node.second, second);
    }
  }
  walk(layout.root, stage);
  for (const floating of layout.floats) {
    rects.set(floating.group.id, {
      x: clamp(floating.x, 0, Math.max(0, stage.w - 100)),
      y: clamp(floating.y, 0, Math.max(0, stage.h - HEADER)),
      w: Math.min(floating.w, stage.w),
      h: Math.min(floating.h, stage.h),
      z: 100 + floating.z * 4,
      floating: true,
    });
  }
  if (maximized && rects.has(maximized)) {
    rects.clear();
    rects.set(maximized, {
      ...stage,
      z: 600,
      floating: layout.floats.some((floating) => floating.group.id === maximized),
    });
  }
  return { rects, splits: maximized ? [] : splits };
}
export function boxStyle(rect: T.Rect, bounds: T.WorkspaceBounds, zIndex = 0): CSSProperties {
  return {
    left: bounds.left + rect.x,
    top: bounds.top + rect.y,
    width: Math.max(0, rect.w),
    height: Math.max(0, rect.h),
    zIndex,
  };
}
