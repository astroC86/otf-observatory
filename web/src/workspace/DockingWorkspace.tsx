import { useRef } from "react";
import { setPreset, useWorkspace } from "./store";
import { useDockRuntime } from "./useDockRuntime";
import DockToolbar from "./DockToolbar";

interface Props {
  active: boolean;
  epoch: number;
}
export default function DockingWorkspace({ active, epoch }: Props) {
  const { expanded, empty } = useWorkspace((state) => ({
    expanded: state.expanded,
    empty: Object.keys(state.layout.panels).length === 0,
  }));
  const stage = useRef<HTMLDivElement>(null);
  useDockRuntime(stage, active, expanded, epoch);
  if (!active) return null;
  return (
    <div className={`dock-workspace${expanded ? " expanded" : ""}`}>
      <DockToolbar />
      <div ref={stage} className="dock-stage" aria-label="Docking workspace">
        <div className="dock-empty" hidden={!empty}>
          <strong>No charts open</strong>
          <span>Choose a chart above to start a workspace.</span>
          <button data-default="" onClick={() => setPreset("Analysis")}>
            Restore analysis layout
          </button>
        </div>
      </div>
      <div className="dock-hint">
        <span>
          Drag a tab to a panel edge to split, or to its center to stack tabs. Shift-drag to float.
          Drag ⠿ to move a group.
        </span>
        <span>Charts share the trace and selection.</span>
      </div>
    </div>
  );
}
