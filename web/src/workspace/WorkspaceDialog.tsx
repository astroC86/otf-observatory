import { useRef, useState } from "react";
import { Dialog } from "../components/ui/Dialog";
import { notify } from "../state/uiActions";
import { download } from "../lib/download";
import * as model from "./layout";
import { dockIds, getWorkspace, loadLayout, saveLayout, updateWorkspace } from "./store";
import type { DockPosition } from "./types";

const positions: [DockPosition, string][] = [
  ["left", "← Left"],
  ["right", "Right →"],
  ["top", "↑ Above"],
  ["bottom", "Below ↓"],
  ["center", "Tab"],
  ["float", "Float"],
];
function readNamed() {
  try {
    return model.record(JSON.parse(localStorage.getItem(model.SAVED) || "{}"));
  } catch {
    return {};
  }
}
export default function WorkspaceDialog({ group: groupId }: { group: string }) {
  const { layout, bounds, maximized } = getWorkspace(),
    live = model.groups(layout);
  const group = live.find((group) => group.id === groupId),
    targets = live.filter((entry) => entry.id !== groupId || entry.tabs.length > 1);
  const [saved, setSaved] = useState(readNamed),
    [name, setName] = useState(() => layout.name || "My workspace");
  const [selected, setSelected] = useState(() => Object.keys(saved)[0] || "");
  const [target, setTarget] = useState(() => targets[0]?.id || ""),
    [error, setError] = useState("");
  const [revision, setRevision] = useState(0),
    file = useRef<HTMLInputElement>(null);
  const close = () => updateWorkspace({ dialog: "" });
  function action(action: string) {
    try {
      if (action === "save") {
        if (!name.trim()) return;
        const layout = { ...getWorkspace().layout, name: name.trim() };
        localStorage.setItem(
          model.SAVED,
          JSON.stringify({ ...readNamed(), [layout.name]: model.copy(layout) }),
        );
        updateWorkspace({ layout });
        saveLayout();
        close();
        notify("Chart layout saved.");
      } else if (action === "load") {
        loadLayout(saved[selected]);
        close();
      } else if (action === "delete") {
        const next = readNamed();
        delete next[selected];
        localStorage.setItem(model.SAVED, JSON.stringify(next));
        setSaved(next);
        setSelected(Object.keys(next)[0] || "");
        setName(getWorkspace().layout.name || "My workspace");
        setRevision((value) => value + 1);
      } else if (action === "export") {
        const layout = getWorkspace().layout;
        download(
          "otf-chart-layout.json",
          JSON.stringify({ ...layout, name: layout.name || "Custom workspace" }, null, 2),
        );
      } else file.current?.click();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (action === "delete") notify(message);
      else setError(message);
    }
  }
  return (
    <Dialog key={revision} open className="dock-dialog" onClose={close}>
      <form method="dialog">
        <div className="dock-dialog-title">
          <h2>{group ? "Arrange chart" : "Saved chart layouts"}</h2>
          <button value="cancel" aria-label="Close dialog">
            ×
          </button>
        </div>
      </form>
      {group ? (
        <>
          <p>
            Move <strong>{model.panelTitle(layout.panels[group.active]!)}</strong> relative to
            another panel, or float it.
          </p>
          <label className="dock-field">
            Target panel
            <select
              data-target=""
              value={target}
              onChange={(event) => setTarget(event.target.value)}
            >
              {targets.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.tabs.map((id) => model.panelTitle(layout.panels[id]!)).join(" / ")}
                </option>
              ))}
            </select>
          </label>
          <div className="dock-arrange-buttons">
            {positions.map(([position, label]) => (
              <button
                key={position}
                data-place={position}
                disabled={position !== "float" && !targets.length}
                onClick={() => {
                  dockIds(
                    [group.active],
                    target,
                    position,
                    model.workspaceGeometry(layout, bounds, maximized).rects.get(groupId),
                  );
                  close();
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <p className="muted">
            Drag tabs for the same actions. Hold Shift while dragging to float a chart.
          </p>
        </>
      ) : (
        <>
          <p>
            The current layout is restored automatically. Named layouts are stored in this browser.
          </p>
          <label className="dock-field">
            Layout name
            <input
              data-name=""
              maxLength={100}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <button className="primary" data-save="" onClick={() => action("save")}>
            Save current layout
          </button>
          <hr />
          <label className="dock-field">
            Saved layout
            <select
              data-saved=""
              value={selected}
              onChange={(event) => setSelected(event.target.value)}
            >
              {Object.keys(saved).length ? (
                Object.keys(saved).map((name) => <option key={name}>{name}</option>)
              ) : (
                <option value="">No saved layouts</option>
              )}
            </select>
          </label>
          <div className="dock-arrange-buttons">
            {[
              ["load", "Load"],
              ["delete", "Delete saved layout"],
              ["export", "Export JSON"],
              ["import", "Import JSON"],
            ].map(([id, label]) => (
              <button
                key={id}
                {...{ [`data-${id}`]: "" }}
                disabled={(id === "load" || id === "delete") && !Object.keys(saved).length}
                onClick={() => action(id!)}
              >
                {label}
              </button>
            ))}
          </div>
          <input
            ref={file}
            type="file"
            accept="application/json,.json"
            data-file=""
            hidden
            onChange={async (event) => {
              const selected = event.target.files?.[0];
              if (!selected) return;
              try {
                if (selected.size > 8 * 1024 * 1024) throw Error("Layout file exceeds 8 MiB.");
                loadLayout(JSON.parse(await selected.text()));
                close();
              } catch (error) {
                setError(error instanceof Error ? error.message : String(error));
              }
            }}
          />
          <p className="dock-dialog-error" role="alert">
            {error}
          </p>
        </>
      )}
    </Dialog>
  );
}
