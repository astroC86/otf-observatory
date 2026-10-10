import { useEffect, useRef, type PointerEvent as ReactPointerEvent } from "react";
import * as model from "./layout";
import {
  activate,
  dockIds,
  editWorkspace,
  getWorkspace,
  idleDrag,
  saveLayout,
  updateWorkspace,
} from "./store";
import type { DockLayout, DropTarget, WorkspaceGeometry } from "./types";

type Drag = {
  kind: "tab" | "group" | "resize" | "split";
  id: string;
  detail: string;
  x: number;
  y: number;
  moved: boolean;
  layout: DockLayout;
  geometry: WorkspaceGeometry;
};
export function useDockPointer() {
  const drag = useRef<Drag | null>(null),
    pending = useRef<PointerEvent | null>(null);
  const target = useRef<DropTarget | null>(null),
    frame = useRef(0);
  useEffect(() => {
    function move(event: PointerEvent) {
      const operation = drag.current;
      if (!operation) return;
      const { bounds, layout, maximized } = getWorkspace(),
        dx = event.clientX - operation.x,
        dy = event.clientY - operation.y;
      if (operation.kind === "split") {
        const split = operation.geometry.splits.find((entry) => entry.node.id === operation.id)!;
        const offset =
          split.node.axis === "x"
            ? event.clientX - bounds.left - split.parent.x
            : event.clientY - bounds.top - split.parent.y;
        editWorkspace((draft) => {
          const node = model.findNode(draft.layout.root, operation.id);
          if (node?.type === "split")
            node.ratio = model.clamp(
              offset /
                Math.max(1, (node.axis === "x" ? split.parent.w : split.parent.h) - model.GAP),
              0.1,
              0.9,
            );
        }, false);
        return;
      }
      if (operation.kind === "resize") {
        const original = operation.layout.floats.find((entry) => entry.group.id === operation.id)!;
        let { x, y, w, h } = original;
        if (operation.detail.includes("e")) w = model.clamp(original.w + dx, 220, bounds.width - x);
        if (operation.detail.includes("s"))
          h = model.clamp(original.h + dy, 150, bounds.height - y);
        if (operation.detail.includes("w")) {
          x = model.clamp(original.x + dx, 0, original.x + original.w - 220);
          w = original.w + original.x - x;
        }
        if (operation.detail.includes("n")) {
          y = model.clamp(original.y + dy, 0, original.y + original.h - 150);
          h = original.h + original.y - y;
        }
        editWorkspace(
          (draft) =>
            Object.assign(
              draft.layout.floats.find((entry) => entry.id === original.id)!,
              { x, y, w, h },
            ),
          false,
        );
        return;
      }
      if (!operation.moved && Math.hypot(dx, dy) < 5) return;
      operation.moved = true;
      const ids =
        operation.kind === "tab"
          ? [operation.detail]
          : model.groups(operation.layout).find((group) => group.id === operation.id)!.tabs;
      const point = { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
      let drop: DropTarget = { position: "float", point };
      if (!event.shiftKey) {
        const candidates = [...model.workspaceGeometry(layout, bounds, maximized).rects]
          .filter(
            ([, rect]) =>
              point.x >= rect.x &&
              point.x <= rect.x + rect.w &&
              point.y >= rect.y &&
              point.y <= rect.y + rect.h,
          )
          .toSorted((a, b) => b[1].z - a[1].z);
        const match = candidates.find(
          ([id]) =>
            !model
              .groups(layout)
              .find((group) => group.id === id)!
              .tabs.every((id) => ids.includes(id)),
        );
        if (match) {
          const [id, rect] = match,
            x = (point.x - rect.x) / rect.w,
            y = (point.y - rect.y) / rect.h;
          drop = {
            target: id,
            position:
              y < 0.22
                ? "top"
                : y > 0.78
                  ? "bottom"
                  : x < 0.25
                    ? "left"
                    : x > 0.75
                      ? "right"
                      : "center",
            rect,
            point,
          };
        } else if (
          layout.root &&
          (point.x < 24 ||
            point.x > bounds.width - 24 ||
            point.y < 24 ||
            point.y > bounds.height - 24)
        ) {
          drop = {
            target: layout.root.id,
            position:
              point.x < 24
                ? "left"
                : point.x > bounds.width - 24
                  ? "right"
                  : point.y < 24
                    ? "top"
                    : "bottom",
            root: true,
            point,
            rect: { x: 0, y: 0, w: bounds.width, h: bounds.height },
          };
        }
      }
      target.current = drop;
      let preview = null;
      if (drop.position !== "float") {
        const rect = { ...drop.rect };
        if (drop.position === "left" || drop.position === "right") rect.w /= 2;
        if (drop.position === "right") rect.x += rect.w;
        if (drop.position === "top" || drop.position === "bottom") rect.h /= 2;
        if (drop.position === "bottom") rect.y += rect.h;
        preview = {
          text: drop.position === "center" ? "Add as tab" : `Dock ${drop.position}`,
          style: model.boxStyle(
            { x: rect.x + 3, y: rect.y + 3, w: rect.w - 6, h: rect.h - 6 },
            bounds,
            10000,
          ),
        };
      }
      updateWorkspace({
        drag: {
          interacting: true,
          label:
            ids.length === 1 ? model.panelTitle(layout.panels[ids[0]!]!) : `${ids.length} charts`,
          left: event.clientX + 14,
          top: event.clientY + 14,
          preview,
        },
      });
    }
    function flush() {
      frame.current = 0;
      if (pending.current) move(pending.current);
      pending.current = null;
    }
    function end(event: { clientX: number; clientY: number }, cancel = false) {
      const operation = drag.current;
      if (!operation) return;
      cancelAnimationFrame(frame.current);
      flush();
      drag.current = null;
      const drop = target.current;
      target.current = null;
      updateWorkspace({ drag: idleDrag });
      if (cancel) {
        editWorkspace((draft) => {
          if (operation.kind === "split") {
            const node = model.findNode(draft.layout.root, operation.id),
              original = model.findNode(operation.layout.root, operation.id);
            if (node?.type === "split" && original?.type === "split") node.ratio = original.ratio;
          } else if (operation.kind === "resize") {
            const original = operation.layout.floats.find(
              (entry) => entry.group.id === operation.id,
            )!;
            Object.assign(
              draft.layout.floats.find((entry) => entry.id === original.id)!,
              original,
            );
          }
        }, false);
      } else if (operation.kind === "split" || operation.kind === "resize") saveLayout();
      else {
        const ids =
          operation.kind === "tab"
            ? [operation.detail]
            : model.groups(operation.layout).find((group) => group.id === operation.id)!.tabs;
        if (!operation.moved) {
          if (ids.length === 1) activate(operation.id, ids[0]!);
          return;
        }
        if (!drop) return;
        const { bounds } = getWorkspace(),
          original = operation.geometry.rects.get(operation.id)!;
        const floating = operation.layout.floats.find((entry) => entry.group.id === operation.id);
        if (drop.position === "float" && floating && operation.kind === "group") {
          editWorkspace((draft) =>
            Object.assign(
              draft.layout.floats.find((entry) => entry.id === floating.id)!,
              {
                x: model.clamp(
                  original.x + event.clientX - operation.x,
                  0,
                  Math.max(0, bounds.width - 100),
                ),
                y: model.clamp(
                  original.y + event.clientY - operation.y,
                  0,
                  Math.max(0, bounds.height - model.HEADER),
                ),
                z: Math.max(0, ...draft.layout.floats.map((entry) => entry.z)) + 1,
              },
            ),
          );
        } else if (drop.position !== "float" && drop.root) {
          editWorkspace((draft) => {
            model.removeTabs(draft.layout, ids);
            const group = model.newGroup(ids),
              first = ["left", "top"].includes(drop.position),
              root = draft.layout.root;
            draft.layout.root = root
              ? {
                  type: "split",
                  id: model.uid("split"),
                  axis: ["left", "right"].includes(drop.position) ? "x" : "y",
                  ratio: 0.5,
                  first: first ? group : root,
                  second: first ? root : group,
                }
              : group;
            draft.focused = group.id;
          });
        } else
          dockIds(ids, drop.position === "float" ? null : drop.target, drop.position, {
            x: model.clamp(drop.point.x - 80, 0, Math.max(0, bounds.width - 220)),
            y: model.clamp(drop.point.y - 18, 0, Math.max(0, bounds.height - 150)),
            w: Math.min(original.w || 560, bounds.width),
            h: Math.min(original.h || 360, bounds.height),
          });
      }
    }
    const queue = (event: PointerEvent) => {
      if (drag.current) {
        pending.current = event;
        if (!frame.current) frame.current = requestAnimationFrame(flush);
      }
    };
    const up = (event: PointerEvent) => end(event),
      cancel = (event: PointerEvent) => end(event, true);
    const key = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (drag.current) {
        event.preventDefault();
        end({ clientX: 0, clientY: 0 }, true);
      } else if (getWorkspace().maximized)
        editWorkspace((draft) => {
          draft.maximized = "";
        });
    };
    window.addEventListener("pointermove", queue);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
    window.addEventListener("keydown", key);
    return () => {
      cancelAnimationFrame(frame.current);
      window.removeEventListener("pointermove", queue);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel);
      window.removeEventListener("keydown", key);
    };
  }, []);
  return (event: ReactPointerEvent<HTMLElement>, kind: Drag["kind"], id: string, detail = "") => {
    if (event.button !== 0) return;
    const state = getWorkspace();
    drag.current = {
      kind,
      id,
      detail,
      x: event.clientX,
      y: event.clientY,
      moved: false,
      layout: state.layout,
      geometry: model.workspaceGeometry(state.layout, state.bounds, state.maximized),
    };
    updateWorkspace({
      focused: kind === "split" ? state.focused : id,
      drag: { ...idleDrag, interacting: kind === "split" || kind === "resize" },
    });
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
  };
}
