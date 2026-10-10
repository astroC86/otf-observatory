import { memo, useLayoutEffect, useState } from "react";
import { Card } from "../../components/panel/Card";
import { ControlBar } from "../../components/controls/ControlBar";
import {
  buttonControl as button,
  numberControl as number,
  checkboxControl as checkbox,
} from "../../components/controls/factories";
import { OptionList } from "../../components/controls/OptionList";
import { Chart } from "../../components/chart/Chart";
import { download } from "../../lib/download";
import { duration } from "../../lib/format/time";
import { getState } from "../../state/store";
import { useStore } from "../../state/useStore";
import { scheduleRender } from "../../state/viewActions";
import { updateQuery } from "../shared/dataControls";
import { EMPTY_MARKER_INPUT, markerIds, setMarkerInput, setMarkerWindow } from "./actions";
import { MarkerRun } from "./MarkerRun";
import { MarkerTables } from "./MarkerTables";
import { drawMarkerTimeline } from "./drawMarkerTimeline";
import { useMarkerAlignment } from "./useMarkerAlignment";
import type { ComparisonProps } from "./types";

export const MarkerPanel = memo(function MarkerPanel({ data, snapshot }: ComparisonProps) {
  const ids = markerIds(snapshot),
    session = data.markerSession,
    result = data.markerResult;
  const [start, setStart] = useState(() =>
    String(result?.range.start ?? getState().markerWindow?.start ?? session?.range.start ?? 0),
  );
  const [end, setEnd] = useState(() =>
    String(result?.range.end ?? getState().markerWindow?.end ?? session?.range.end ?? 0),
  );
  const windowStart = result?.range.start ?? snapshot.markerWindow?.start ?? session?.range.start;
  const windowEnd = result?.range.end ?? snapshot.markerWindow?.end ?? session?.range.end;
  useLayoutEffect(() => {
    setStart(String(windowStart ?? 0));
    setEnd(String(windowEnd ?? 0));
  }, [windowStart, windowEnd]);
  const selectedLocation = useStore((state) => state.markerSelectedLocationOnly);
  const apply = useMarkerAlignment();
  const disabled = ids.length < 2 || apply.isPending;
  return (
    <Card title="Align traces at markers">
      {ids.map((id, index) => (
        <MarkerRun
          key={id}
          id={id}
          index={index}
          name={data.archives.find((trace) => trace.id === id)?.name || ""}
        />
      ))}
      <ControlBar
        controls={[
          button("marker-align", "Align selected markers", () => apply.mutate("align"), {
            className: "primary",
            disabled,
          }),
          button("marker-manual", "Apply display offsets", () => apply.mutate("manual"), {
            disabled,
          }),
          button("marker-reset", "Reset offsets", () => apply.mutate("reset"), { disabled }),
          ...(session
            ? [
                button("marker-export", "Export marker alignment", () =>
                  download(
                    "marker-alignment.json",
                    JSON.stringify({ ...session, window: getState().markerWindow }, null, 2),
                  ),
                ),
              ]
            : []),
        ]}
      />
      <p className="muted card-description">
        {
          "Select comparison runs above. Alignment moves every selected marker to the earliest current marker position, clamped to zero. Each run keeps its physical durations."
        }
      </p>
      {session && (
        <>
          <ControlBar
            controls={[
              number("marker-window-start", "Display from", start, setStart, { suffix: " s" }),
              number("marker-window-end", "to", end, setEnd, { suffix: " s" }),
              button("marker-window-apply", "Apply shared window", () =>
                setMarkerWindow(Number(start), Number(end)),
              ),
              button("marker-fit", "Fit all runs", () =>
                setMarkerWindow(session.range.start, session.range.end),
              ),
              checkbox(
                "marker-profile-location",
                "Profiles use selected timeline locations",
                selectedLocation,
                (checked) => updateQuery({ markerSelectedLocationOnly: checked }),
                { labelClassName: "check", labelAfter: true },
              ),
            ]}
          />
          <p className="muted card-description">{`${session.target != null ? `Selected markers align at ${duration(session.target)}. ` : ""}Drag across the chart to zoom all runs together; Shift-drag pans. Global function filters apply to every run.`}</p>
        </>
      )}
      {data.markerError && (
        <p className="analysis-warning" role="alert">
          {data.markerError}
        </p>
      )}
      {result && session && (
        <>
          <div className="marker-locations">
            {result.runs.map((run, index) => (
              <label key={run.id}>
                {`${index ? `Run ${index}` : "Baseline"} timeline location`}
                <select
                  data-marker-location={run.id}
                  defaultValue={run.location || ""}
                  onChange={(event) => {
                    setMarkerInput(run.id, {
                      ...(getState().markerInputs[run.id] || EMPTY_MARKER_INPUT),
                      location: event.target.value,
                    });
                    scheduleRender();
                  }}
                >
                  <OptionList
                    items={run.locations.map((location) => [location.id, location.name] as const)}
                  />
                </select>
              </label>
            ))}
          </div>
          <div className="chart-wrap">
            <Chart
              id="marker-timeline"
              aria-label="Marker aligned execution timelines"
              draw={(element) => drawMarkerTimeline(element, result, session)}
              deps={[result, session]}
            />
          </div>
          <MarkerTables result={result} />
        </>
      )}
    </Card>
  );
});
