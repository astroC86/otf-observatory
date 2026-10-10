import { compact } from "../../lib/format/numbers";
import { setView } from "../../state/viewActions";
import { shortLoc } from "../../state/selectors";
import { useExport } from "../../hooks/useExport";
import { Card } from "../../components/panel/Card";
import { Chart } from "../../components/chart/Chart";
import { ChartGroup } from "../../components/chart/ChartGroup";
import { ControlBar } from "../../components/controls/ControlBar";
import type { Option } from "../../components/controls/types";
import type { MessagesResponse } from "../../api/types/data";
import type { ViewState } from "../../state/types";
import type { FunctionSummaryRow, TimelineResponse } from "../../api/types/execution";
import { change } from "../executionState";
import { selectControl, checkboxControl, buttonControl } from "../../components/controls/factories";

export type TimelineData = readonly [
  TimelineResponse,
  readonly FunctionSummaryRow[],
  MessagesResponse,
];
interface TimelinePanelProps {
  result: TimelineData;
  state: ViewState;
  locations: readonly string[];
  visible: readonly string[];
  detailLocation: string | null;
}

export function TimelinePanel({
  result: [data, summary, messages],
  state,
  locations,
  visible,
  detailLocation,
}: TimelinePanelProps) {
  const detail = detailLocation != null;
  useExport<object>(data.rows, "timeline");
  return (
    <>
      <Card
        title={detail ? "Process timeline" : "Master timeline"}
        controls={[
          selectControl(
            "timeline-mode",
            undefined,
            locations.find((location) => location === detailLocation) ?? "",
            [
              ["", "Master timeline"],
              ...locations.map((location): Option => [
                location,
                `${shortLoc(location)} · call stack`,
              ]),
            ],
            (value) => change({ detailLocation: value || null }),
            {
              ariaLabel: "Timeline mode",
            },
          ),
          selectControl(
            "color-by",
            undefined,
            state.groupBy,
            [
              ["function", "Color by function"],
              ["group", "Color by group"],
            ],
            (value) => change({ groupBy: value }),
            {
              ariaLabel: "Color timeline by",
            },
          ),
          checkboxControl(
            "message-arrows",
            "Messages",
            state.showMessages,
            (checked) => change({ showMessages: checked }),
            {
              labelAfter: true,
              labelClassName: "check",
            },
          ),
        ]}
        caption={
          <>
            <span>{`${detail ? "Nested call stack" : `${visible.length} of ${locations.length} execution locations`} · ${data.truncated ? "Display limit reached; zoom in for all events." : "Subpixel calls coalesce; statistics use all events."}${state.showMessages ? " · First 500 matching message arrows." : ""}`}</span>
            {!detail && locations.length > 24 ? (
              <span className="pager">
                <ControlBar
                  className={null}
                  controls={[
                    buttonControl(
                      "timeline-prev",
                      "←",
                      () =>
                        change((previous) => ({
                          timelinePage: previous.timelinePage - 1,
                        })),
                      {
                        disabled: state.timelinePage === 0,
                      },
                    ),
                    {
                      kind: "content",
                      children: <span>{`Page ${state.timelinePage + 1}`}</span>,
                    },
                    buttonControl(
                      "timeline-next",
                      "→",
                      () =>
                        change((previous) => ({
                          timelinePage: previous.timelinePage + 1,
                        })),
                      {
                        disabled: (state.timelinePage + 1) * 24 >= locations.length,
                      },
                    ),
                  ]}
                />
              </span>
            ) : null}
          </>
        }
      >
        <div className="chart-wrap">
          <Chart
            id="timeline-chart"
            role="img"
            aria-label="Execution timeline"
            spec={{
              type: "timeline",
              data,
              visible,
              detail,
              messages: messages.rows,
            }}
          />
        </div>
      </Card>
      <ChartGroup className="dashboard-grid">
        <Card
          title={
            <>
              {`Function profile `}
              <span className="muted">{`exclusive time`}</span>
            </>
          }
          controls={[buttonControl("all-functions", "View all →", () => setView("functions"))]}
        >
          <Chart
            id="profile-chart"
            aria-label="Top functions by exclusive time"
            spec={{ type: "bars", data: summary }}
          />
        </Card>
        <Card
          title={
            <>
              {`Communication matrix `}
              <span className="muted">
                {`${state.matrixMetric === "bytes" ? "bytes transferred" : state.matrixMetric === "count" ? "message count" : "mean transfer time"}`}
              </span>
            </>
          }
          controls={[
            buttonControl("all-messages", `${compact(messages.total)} messages →`, () =>
              setView("communication"),
            ),
          ]}
        >
          <Chart
            id="mini-matrix"
            aria-label="MPI communication matrix"
            spec={{ type: "matrix", data: messages.matrix, compact: true }}
          />
        </Card>
      </ChartGroup>
    </>
  );
}
