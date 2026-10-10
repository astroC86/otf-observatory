import type { SpanResponse } from "../api/types/common";
import { ControlBar } from "../components/controls/ControlBar";
import { KeyValueList } from "../components/ui/KeyValueList";
import { duration } from "../lib/format/time";
import { locName } from "../state/selectors";
import { scheduleRender, setView } from "../state/viewActions";
import { setRange } from "../state/rangeActions";
import { updateState } from "../state/store";
import { buttonControl } from "../components/controls/factories";

interface SpanContextProps {
  span: SpanResponse;
}

export default function SpanContext({ span }: SpanContextProps) {
  const fields = {
    Location: locName(span.location),
    Start: duration(span.start),
    End: duration(span.end),
    Inclusive: duration(span.end - span.start),
    Exclusive: duration(span.exclusive),
    Depth: span.depth,
    "Call path": span.path,
    Source: span.regionDefinition?.file
      ? `${span.regionDefinition.file}:${span.regionDefinition.line}`
      : "Not recorded",
    State: span.incomplete
      ? "Incomplete"
      : span.sampled
        ? "Sampled estimate"
        : span.continuation
          ? "Resumed task segment"
          : "Complete",
  };
  return (
    <>
      <div className="eyebrow">{span.regionDefinition?.group}</div>
      <h3>{span.regionDefinition?.name || span.region}</h3>
      <KeyValueList
        className={null}
        items={Object.entries(fields).map(([label, value]) => ({
          label,
          value: String(value ?? ""),
        }))}
      />
      <ControlBar
        className="context-actions"
        controls={[
          buttonControl("context-zoom", "Zoom to call", () => setRange(span.start, span.end)),
          buttonControl("context-process", "Process timeline", () => {
            updateState({ detailLocation: span.location });
            setView("timeline");
          }),
          buttonControl("context-filter", "Filter function", () => {
            updateState({ region: span.regionDefinition?.name || "" });
            scheduleRender();
          }),
        ]}
      />
      <h3>Associated records</h3>
      {span.events.map((event, index) => (
        <details key={index}>
          <summary>{`${event.kind} · ${duration(event.time)}`}</summary>
          <pre className="code-block">{JSON.stringify(event, null, 2)}</pre>
        </details>
      ))}
    </>
  );
}
