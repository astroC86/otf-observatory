import { useMemo } from "react";
import { useUi } from "../state/useUi";
import * as model from "./layout";
import {
  activate,
  closePanel,
  dockIds,
  editWorkspace,
  getWorkspace,
  updateWorkspace,
  useWorkspace,
} from "./store";
import { registerFrame } from "./useDockRuntime";
import { useDockPointer } from "./useDockPointer";
import WorkspaceDialog from "./WorkspaceDialog";

const edges = ["n", "s", "e", "w", "ne", "nw", "se", "sw"];
export default function DockingLayer() {
  const embedded = useUi((ui) => ui.embedded);
  const [
    layout,
    bounds,
    active,
    focused,
    maximized,
    frames,
    drag,
    dialog,
    target,
    announcement,
    order,
  ] = useWorkspace(
    (state) =>
      [
        state.layout,
        state.bounds,
        state.active,
        state.focused,
        state.maximized,
        state.frames,
        state.drag,
        state.dialog,
        state.target,
        state.announcement,
        state.poolOrder,
      ] as const,
  );
  const begin = useDockPointer();
  const geometry = useMemo(
    () => model.workspaceGeometry(layout, bounds, maximized),
    [layout, bounds, maximized],
  );
  if (embedded) return null;
  const live = model.groups(layout);
  function action(name: string, id: string) {
    const state = getWorkspace(),
      group = model.groups(state.layout).find((group) => group.id === id)!;
    updateWorkspace({ focused: id });
    if (name === "arrange") updateWorkspace({ dialog: "arrange", target: id });
    if (name === "close") closePanel(group.active);
    if (name === "maximize")
      editWorkspace((draft) => {
        draft.maximized = draft.maximized === id ? "" : id;
      });
    if (name === "float") {
      if (state.layout.floats.some((entry) => entry.group.id === id))
        dockIds([...group.tabs], model.allGroups(state.layout.root)[0]?.id || null);
      else dockIds([group.active], null, "float", geometry.rects.get(id));
    }
  }
  const items = new Map(
    [
      ...live.map((group) => {
        const rect = geometry.rects.get(group.id),
          floating = layout.floats.some((entry) => entry.group.id === group.id);
        const maximize = maximized === group.id ? "Restore panel" : "Maximize panel";
        const buttons = [
          ["arrange", "Arrange or move chart", "Arrange chart", "⋮"],
          [
            "float",
            floating ? "Dock this group" : "Float active chart",
            floating ? "Dock group" : "Float chart",
            "↗",
          ],
          ["maximize", maximize, maximize, maximized === group.id ? "❐" : "□"],
          ["close", "Close active chart", "Close active chart", "×"],
        ];
        return (
          <section
            key={`pane:${group.id}`}
            className={`dock-pane${floating ? " floating" : ""}${focused === group.id ? " focused" : ""}`}
            data-group-id={group.id}
            hidden={!rect}
            style={rect ? model.boxStyle(rect, bounds, rect.z + 2) : undefined}
            aria-label={`${group.tabs.map((id) => model.panelTitle(layout.panels[id]!)).join(", ")} panel`}
          >
            <div
              className="dock-pane-header"
              onDoubleClick={(event) => {
                if ((event.target as Element).closest(".dock-tab,.dock-grip"))
                  action("maximize", group.id);
              }}
            >
              <button
                className="dock-grip"
                data-action="drag-group"
                title="Drag this tab group"
                aria-label="Move tab group"
                onPointerDown={(event) => begin(event, "group", group.id)}
              >
                ⠿
              </button>
              <div className="dock-tabs" role="tablist" aria-label="Charts in panel">
                {group.tabs.map((id) => (
                  <button
                    key={id}
                    className={`dock-tab ${group.active === id ? "active" : ""}`}
                    role="tab"
                    aria-selected={group.active === id}
                    data-panel={id}
                    title={`${model.panelTitle(layout.panels[id]!)} — drag to dock`}
                    onPointerDown={(event) => begin(event, "tab", group.id, id)}
                    onClick={(event) => {
                      activate(group.id, id);
                      if (!event.detail) event.currentTarget.focus({ preventScroll: true });
                    }}
                    onKeyDown={(event) => {
                      if (!["Home", "End", "ArrowLeft", "ArrowRight"].includes(event.key)) return;
                      event.preventDefault();
                      const index =
                        event.key === "Home"
                          ? 0
                          : event.key === "End"
                            ? group.tabs.length - 1
                            : (group.tabs.indexOf(id) +
                                (event.key === "ArrowLeft" ? -1 : 1) +
                                group.tabs.length) %
                              group.tabs.length;
                      activate(group.id, group.tabs[index]!);
                      event.currentTarget.parentElement
                        ?.querySelector<HTMLButtonElement>(`[data-panel="${group.tabs[index]}"]`)
                        ?.focus({ preventScroll: true });
                    }}
                  >
                    <span>{model.panelTitle(layout.panels[id]!)}</span>
                  </button>
                ))}
              </div>
              <div className="dock-pane-actions">
                {buttons.map(([name, title, label, icon]) => (
                  <button
                    key={name}
                    data-action={name}
                    title={title}
                    aria-label={label}
                    onClick={() => action(name!, group.id)}
                  >
                    {icon}
                  </button>
                ))}
              </div>
            </div>
            {floating &&
              edges.map((edge) => (
                <div
                  key={edge}
                  className={`dock-float-resize dock-resize-${edge}`}
                  data-resize={edge}
                  onPointerDown={(event) => begin(event, "resize", group.id, edge)}
                />
              ))}
          </section>
        );
      }),
      ...frames.map((source) => {
        const group = live.find((group) => group.active === source.id),
          rect = group && geometry.rects.get(group.id);
        return (
          <iframe
            key={`frame:${source.id}`}
            ref={registerFrame}
            className="dock-chart-frame"
            title={`${model.panelTitle(layout.panels[source.id]!)} chart`}
            data-panel-id={source.id}
            src={source.url}
            hidden={!active || !rect || rect.h <= model.HEADER || rect.w < 10}
            referrerPolicy="same-origin"
            style={
              rect
                ? model.boxStyle(
                    {
                      x: rect.x + 1,
                      y: rect.y + model.HEADER,
                      w: rect.w - 2,
                      h: rect.h - model.HEADER - 1,
                    },
                    bounds,
                    rect.z + 1,
                  )
                : undefined
            }
          />
        );
      }),
      ...geometry.splits.map((split) => (
        <div
          key={`split:${split.node.id}`}
          className={`dock-splitter${split.node.axis === "x" ? " vertical" : ""}`}
          tabIndex={0}
          role="separator"
          data-split={split.node.id}
          aria-orientation={split.node.axis === "x" ? "vertical" : "horizontal"}
          aria-label="Resize chart split"
          aria-valuenow={Math.round(split.node.ratio * 100)}
          aria-valuemin={10}
          aria-valuemax={90}
          style={model.boxStyle(split.rect, bounds, 50)}
          onPointerDown={(event) => begin(event, "split", split.node.id)}
          onKeyDown={(event) => {
            const keys =
              split.node.axis === "x" ? ["ArrowLeft", "ArrowRight"] : ["ArrowUp", "ArrowDown"];
            if (!keys.includes(event.key)) return;
            event.preventDefault();
            editWorkspace((draft) => {
              const node = model.findNode(draft.layout.root, split.node.id);
              if (node?.type === "split")
                node.ratio = model.clamp(
                  node.ratio + (event.key === keys[0] ? -0.03 : 0.03),
                  0.1,
                  0.9,
                );
            });
          }}
        />
      )),
    ].map((node) => [node.key, node]),
  );
  return (
    <div style={{ display: "contents" }}>
      <div
        className={`dock-pool${drag.interacting ? " interacting" : ""}`}
        hidden={!active}
        aria-label="Docked chart panels"
        style={{ clipPath: bounds.clipPath }}
      >
        <div className="dock-drop-preview" hidden={!drag.preview} style={drag.preview?.style}>
          {drag.preview?.text}
        </div>
        {order.map((key) => items.get(key))}
      </div>
      <div
        className="dock-drag-label"
        hidden={!drag.label}
        style={{ left: drag.left, top: drag.top }}
      >
        {drag.label}
      </div>
      <div className="dock-drag-shield" hidden={!drag.interacting} />
      <div className="dock-sr-only" aria-live="polite">
        {announcement}
      </div>
      {dialog && <WorkspaceDialog group={dialog === "arrange" ? target : ""} />}
    </div>
  );
}
