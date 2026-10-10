import { ControlBar } from "../components/controls/ControlBar";
import type { ControlSpec } from "../components/controls/types";
import { addBookmark } from "../state/bookmarks";
import { moveHistory, setRange, zoom } from "../state/rangeActions";
import { notify } from "../state/uiActions";
import { showExportMenu } from "../state/inspection";
import { updateUi } from "../state/store";
import { useStore } from "../state/useStore";
import { useUi } from "../state/useUi";
import { buttonControl, numberControl } from "../components/controls/factories";

export default function RangeBar() {
  const state = useStore(({ meta, historyIndex, history }) => ({
    meta,
    historyIndex,
    history,
  }));
  const { rangeStart, rangeEnd } = useUi(({ rangeStart, rangeEnd }) => ({
    rangeStart,
    rangeEnd,
  }));
  const apply = () => {
    const start = Number(rangeStart),
      end = Number(rangeEnd);
    if (!Number.isFinite(start + end) || end <= start) {
      notify("Enter a finite end time after the start time.");
      return;
    }
    setRange(start, end);
  };
  const history: ControlSpec[] = [
    buttonControl("back", "↶", () => moveHistory(-1), {
      title: "Previous time range (Alt+Left)",
      ariaLabel: "Previous time range",
      disabled: state.meta ? state.historyIndex <= 0 : undefined,
    }),
    buttonControl("forward", "↷", () => moveHistory(1), {
      title: "Next time range (Alt+Right)",
      ariaLabel: "Next time range",
      disabled: state.meta ? state.historyIndex >= state.history.length - 1 : undefined,
    }),
  ];
  const zoomControls: ControlSpec[] = [
    buttonControl("zoom-in", "＋", () => zoom(0.5), {
      title: "Zoom in (+)",
      ariaLabel: "Zoom in",
    }),
    buttonControl("zoom-out", "−", () => zoom(2), {
      title: "Zoom out (-)",
      ariaLabel: "Zoom out",
    }),
    buttonControl(
      "reset-zoom",
      "Fit trace",
      () => {
        if (state.meta) setRange(0, state.meta.duration);
      },
      {
        title: "Show whole trace (Home)",
      },
    ),
  ];
  const controls: ControlSpec[] = [
    numberControl("range-start", "From", rangeStart, (value) => updateUi({ rangeStart: value }), {
      min: "0",
      step: "any",
      ariaLabel: "Time range start in seconds",
      event: "input",
    }),
    numberControl("range-end", "to", rangeEnd, (value) => updateUi({ rangeEnd: value }), {
      min: "0",
      step: "any",
      ariaLabel: "Time range end in seconds",
      event: "input",
    }),
    {
      kind: "content",
      key: "unit",
      children: <span className="muted">s</span>,
    },
    buttonControl("apply-range", "Apply", apply, {
      className: "quiet",
    }),
    {
      kind: "content",
      key: "spacer",
      children: <div className="header-spacer" />,
    },
    buttonControl("bookmark", "⚑ Bookmark", addBookmark, {
      title: "Bookmark current range (B)",
    }),
    buttonControl("export", "↓ Export", showExportMenu, {
      title: "Export this view",
    }),
  ];
  return (
    <div className="range-toolbar">
      <ControlBar className="button-group" controls={history} />
      <ControlBar className="button-group" controls={zoomControls} />
      <ControlBar className={null} controls={controls} />
    </div>
  );
}
