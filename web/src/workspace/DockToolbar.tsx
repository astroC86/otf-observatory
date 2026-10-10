import * as model from "./layout";
import { addPanel, getWorkspace, setPreset, updateWorkspace, useWorkspace } from "./store";
import type { DockPosition } from "./types";

// Choices live in the store: vanilla reused one detached toolbar across view switches.
export default function DockToolbar() {
  const { name, count, expanded, chart, position } = useWorkspace((state) => ({
    name: state.layout.name,
    count: Object.keys(state.layout.panels).length,
    expanded: state.expanded,
    chart: state.pickedChart,
    position: state.pickedPosition,
  }));
  return (
    <div className="dock-toolbar">
      <div className="dock-add-chart">
        <label className="dock-sr-only" htmlFor="dock-chart-picker">
          Chart type
        </label>
        <select
          id="dock-chart-picker"
          data-chart=""
          value={chart}
          onChange={(event) => updateWorkspace({ pickedChart: event.target.value })}
        >
          <optgroup label="Individual charts">
            {model.charts.map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </optgroup>
          <optgroup label="Complete analysis views">
            {model.knownViews().map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </optgroup>
        </select>
        <label className="dock-sr-only" htmlFor="dock-add-position">
          Add position
        </label>
        <select
          id="dock-add-position"
          data-position=""
          value={position}
          onChange={(event) =>
            updateWorkspace({ pickedPosition: event.target.value as DockPosition })
          }
        >
          <option value="center">As tab</option>
          <option value="right">On right</option>
          <option value="bottom">Below</option>
          <option value="float">Floating</option>
        </select>
        <button className="primary" data-add="" onClick={() => addPanel(chart, position)}>
          ＋ Add chart
        </button>
      </div>
      <div className="dock-layout-actions">
        <label className="dock-sr-only" htmlFor="dock-preset">
          Workspace preset
        </label>
        <select
          id="dock-preset"
          data-preset=""
          value={model.presets.includes(name) ? name : ""}
          onChange={(event) => {
            if (event.target.value) setPreset(event.target.value);
          }}
        >
          <option value="">Custom layout</option>
          {model.presets.map((preset) => (
            <option key={preset}>{preset}</option>
          ))}
        </select>
        <button data-layouts="" onClick={() => updateWorkspace({ dialog: "saved" })}>
          Layouts…
        </button>
        <button
          data-expand=""
          title="Give charts more vertical space"
          aria-pressed={expanded}
          onClick={() => updateWorkspace({ expanded: !getWorkspace().expanded })}
        >
          {expanded ? "Compact" : "Expand"}
        </button>
        <span data-chart-count="" className="muted">{`${count} charts`}</span>
      </div>
    </div>
  );
}
