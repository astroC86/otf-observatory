import { useMemo } from "react";
import { ControlBar } from "../../components/controls/ControlBar";
import { Legend } from "../../components/ui/Legend";
import type { ControlSpec } from "../../components/controls/types";
import { groupColor } from "../../state/selectors";
import { scheduleRender } from "../../state/viewActions";
import { updateState, updateUi } from "../../state/store";
import { useStore } from "../../state/useStore";
import { useUi } from "../../state/useUi";
import { selectControl, checkboxControl } from "../../components/controls/factories";

export default function Filters() {
  const state = useStore(({ meta, region, exclude, group }) => ({
    meta,
    region,
    exclude,
    group,
  }));
  const { showMetrics } = useUi(({ showMetrics }) => ({ showMetrics }));
  const regionGroups = useMemo(
    () => [...new Set(state.meta?.regions.map((region) => region.group) || [])],
    [state.meta],
  );
  const change = (key: "region" | "exclude" | "group", value: string) => {
    updateState({ [key]: value });
    scheduleRender();
  };
  const controls: ControlSpec[] = [
    {
      kind: "search",
      id: "function-filter",
      placeholder: "Include function name…",
      ariaLabel: "Include function name",
      value: state.region,
      onChange: (value) => change("region", value),
    },
    {
      kind: "search",
      id: "exclude-filter",
      placeholder: "Exclude function name…",
      ariaLabel: "Exclude function name",
      value: state.exclude,
      onChange: (value) => change("exclude", value),
    },
    selectControl(
      "group-filter",
      undefined,
      state.group,
      [["", "All function groups"], ...regionGroups],
      (value) => change("group", value),
      {
        ariaLabel: "Function group",
      },
    ),
  ];
  return (
    <div className="sidebar-bottom">
      <div className="section-label">
        FUNCTION FILTERS{" "}
        <button
          id="clear-filters"
          onClick={() => {
            updateState({ region: "", exclude: "", group: "" });
            scheduleRender();
          }}
        >
          Clear
        </button>
      </div>
      <ControlBar className={null} controls={controls} />
      <div className="section-label legend-title">FUNCTION LEGEND</div>
      <Legend
        id="legend"
        items={regionGroups.map((group) => ({
          label: group,
          color: groupColor(group),
          "data-group": group,
          title: `Filter ${group}`,
        }))}
        onClick={(group) => {
          updateState((previous) => ({
            group: previous.group === group ? "" : group,
          }));
          scheduleRender();
        }}
      />
      <ControlBar
        className={null}
        controls={[
          checkboxControl(
            "show-sidebar-metrics",
            "Show metric recorders",
            showMetrics,
            (checked) => updateUi({ showMetrics: checked }),
            {
              labelAfter: true,
              labelClassName: "check",
            },
          ),
        ]}
      />
    </div>
  );
}
