import { Chart } from "../components/chart/Chart";
import { Tabs } from "../components/ui/Tabs";
import { duration } from "../lib/format/time";
import { setView, views } from "../state/viewActions";
import DockingWorkspace from "../workspace/DockingWorkspace";
import { ViewHost } from "../views/ViewHost";
import { useCommittedView } from "../state/useCommittedView";
import { useStore } from "../state/useStore";
import { useUi } from "../state/useUi";
import Footer from "./Footer";
import RangeBar from "./RangeBar";

export default function Workspace() {
  const state = useStore(({ meta, view, start, end, colors }) => ({
    meta,
    view,
    start,
    end,
    colors,
  }));
  const ui = useUi(({ selection, initialized, overviewData, busy }) => ({
    selection,
    initialized,
    overviewData,
    busy,
  }));
  const committed = useCommittedView();
  const warnings = Object.values(state.meta?.warnings || {});
  return (
    <main>
      <div className="workspace-heading">
        <div>
          <div className="eyebrow">PERFORMANCE ANALYSIS</div>
          <h1 id="view-title">
            {views.find((view) => view[0] === state.view)?.[2] || "Execution timeline"}
          </h1>
        </div>
        <div id="selection-description" className="selection-description">
          {ui.selection}
        </div>
      </div>
      <div className="navigation-wrap">
        <Tabs
          as="nav"
          id="view-nav"
          aria-label="Analysis views"
          className={null}
          dataKey="view"
          items={ui.initialized ? views.map(([id, label]) => [id, label]) : []}
          value={state.view}
          onChange={setView}
        />
      </div>
      <RangeBar />
      <div className="overview-wrap">
        <Chart
          id="overview"
          className={null}
          aria-label="Trace overview. Drag to select a time range."
          role="img"
          spec={{ type: "overview" }}
          deps={[state.start, state.end, state.meta, state.colors, ui.overviewData]}
        />
        <div className="overview-caption">
          <span>FULL TRACE</span>
          <span id="overview-range">
            {state.meta ? `0 s — ${duration(state.meta.duration)}` : "—"}
          </span>
        </div>
      </div>
      <div id="notice" className="notice" hidden={!warnings.length}>
        {warnings.length
          ? `${warnings.reduce((sum, value) => sum + value, 0)} trace diagnostics. Open Trace for details.`
          : ""}
      </div>
      <section id="view" className="view" aria-live="polite" aria-busy={ui.busy}>
        <DockingWorkspace active={state.view === "workspace"} epoch={committed?.epoch ?? 0} />
        <ViewHost />
      </section>
      <Footer />
    </main>
  );
}
