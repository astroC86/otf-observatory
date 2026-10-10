import { Fragment, useDeferredValue, useMemo } from "react";
import { ControlBar } from "../../components/controls/ControlBar";
import { StatGrid } from "../../components/ui/StatGrid";
import { compact } from "../../lib/format/numbers";
import { duration } from "../../lib/format/time";
import { groups, locName } from "../../state/selectors";
import { setLocationSelected, selectLocations } from "../../state/filterActions";
import { toggleSidebar } from "../../state/uiActions";
import { getState, updateUi } from "../../state/store";
import { useStore } from "../../state/useStore";
import { useUi } from "../../state/useUi";
import Filters from "./Filters";
import { buttonControl } from "../../components/controls/factories";

export default function Explorer() {
  const state = useStore(({ meta, locations }) => ({ meta, locations }));
  const { meta } = state;
  const { explorerSearch, showMetrics, sidebarCollapsed } = useUi(
    ({ explorerSearch, showMetrics, sidebarCollapsed }) => ({
      explorerSearch,
      showMetrics,
      sidebarCollapsed,
    }),
  );
  const deferredSearch = useDeferredValue(explorerSearch);
  const filtered = useMemo(() => {
    const search = deferredSearch.toLowerCase();
    return (
      meta?.locations.filter(
        (location) =>
          (showMetrics || location.type !== "METRIC") &&
          locName(location.id).toLowerCase().includes(search),
      ) || []
    );
  }, [meta, deferredSearch, showMetrics]);
  const selectAll = (all: boolean) => {
    const meta = getState().meta;
    if (all && !meta) return;
    selectLocations(all ? meta?.locations.map((location) => location.id) || [] : []);
  };
  return (
    <aside className="sidebar">
      <div className="sidebar-heading">
        <span>TRACE EXPLORER</span>
        <button
          id="toggle-sidebar"
          className="icon-button"
          title="Collapse explorer"
          aria-label="Collapse explorer"
          onClick={toggleSidebar}
        >
          {sidebarCollapsed ? "›" : "‹"}
        </button>
      </div>
      <StatGrid
        variant="facts"
        items={[
          {
            id: "duration-fact",
            value: meta ? duration(meta.duration) : "—",
            label: "duration",
          },
          {
            id: "events-fact",
            value: meta ? compact(meta.counts.events) : "—",
            label: "events",
          },
        ]}
      />
      <label className="search-box">
        <span>⌕</span>
        <input
          id="location-search"
          type="search"
          placeholder="Find a process or thread"
          aria-label="Find a process or thread"
          value={explorerSearch}
          onChange={(event) => updateUi({ explorerSearch: event.currentTarget.value })}
        />
      </label>
      <div className="section-label">
        <span>
          LOCATIONS{" "}
          <small id="location-count">
            {meta ? `${state.locations.size}/${meta.locations.length}` : ""}
          </small>
        </span>
        <div>
          <ControlBar
            className={null}
            controls={[
              buttonControl("all-locations", "All", () => selectAll(true)),
              buttonControl("no-locations", "None", () => selectAll(false)),
            ]}
          />
        </div>
      </div>
      <div id="location-tree" className="location-tree">
        {meta ? (
          filtered.map((location, index) => (
            <Fragment key={location.id}>
              {location.group !== filtered[index - 1]?.group && (
                <div className="location-group" title={groups[location.group]?.name || ""}>
                  {`▾ ${groups[location.group]?.name || "Process " + location.group}`}
                </div>
              )}
              <label className="location-row" title={`${locName(location.id)} · ID ${location.id}`}>
                <input
                  type="checkbox"
                  data-location={location.id}
                  checked={state.locations.has(location.id)}
                  onChange={(event) =>
                    setLocationSelected(location.id, event.currentTarget.checked)
                  }
                />
                <span>{location.name}</span>
                <small>
                  {location.type === "METRIC" ? "M" : location.type === "GPU" ? "GPU" : location.id}
                </small>
              </label>
            </Fragment>
          ))
        ) : (
          <p className="muted">Load an archive to explore its processes and threads.</p>
        )}
      </div>
      <Filters />
    </aside>
  );
}
