import type { CSSProperties } from "react";

export interface PanelChoice {
  view: string;
  chart?: string;
}
export interface DockPanel extends PanelChoice {
  id: string;
  settings: Record<string, unknown>;
}
export interface DockGroup {
  type: "group";
  id: string;
  tabs: string[];
  active: string;
}
export interface DockSplit {
  type: "split";
  id: string;
  axis: "x" | "y";
  ratio: number;
  first: DockNode;
  second: DockNode;
}
export type DockNode = DockGroup | DockSplit;
export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}
export interface DockFloat extends Rect {
  id: string;
  group: DockGroup;
  z: number;
}
export interface DockLayout {
  version: 1;
  root: DockNode | null;
  floats: DockFloat[];
  panels: Record<string, DockPanel>;
  name: string;
}
export type DockPosition = "center" | "left" | "right" | "top" | "bottom" | "float";
export interface PaneRect extends Rect {
  z: number;
  floating?: boolean;
}
export interface SplitGeometry {
  node: DockSplit;
  rect: Rect;
  parent: Rect;
}
export interface WorkspaceBounds {
  left: number;
  top: number;
  width: number;
  height: number;
  clipPath: string;
}
export interface WorkspaceGeometry {
  rects: Map<string, PaneRect>;
  splits: SplitGeometry[];
}
export type DropTarget =
  | { position: "float"; point: { x: number; y: number } }
  | {
      position: Exclude<DockPosition, "float">;
      point: { x: number; y: number };
      target: string;
      rect: Rect;
      root?: boolean;
    };
export interface DragDisplay {
  interacting: boolean;
  label: string;
  left: number;
  top: number;
  preview: { text: string; style: CSSProperties } | null;
}
export interface FrameSource extends PanelChoice {
  id: string;
  url: string;
}
export interface DockingApi {
  getLayout(): DockLayout;
  addPanel(
    view?: string | PanelChoice,
    position?: DockPosition,
    target?: string | null,
  ): string | null;
  dockPanel(id: string, target: string | null, position?: DockPosition): void;
  floatPanel(id: string): void;
  closePanel(id: string): void;
  setPreset(name: string): void;
  saveLayout(): void;
  loadLayout(raw: unknown): void;
  broadcast(): void;
}

declare global {
  interface Window {
    otfDocking?: DockingApi;
  }
}
