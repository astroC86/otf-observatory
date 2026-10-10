import { Dialog } from "../components/ui/Dialog";
import { getUi, updateUi } from "../state/store";
import { useUi } from "../state/useUi";

export default function HelpDialog() {
  const { dialog } = useUi(({ dialog }) => ({ dialog }));
  return (
    <Dialog
      id="help-dialog"
      open={dialog === "help"}
      onClose={() => {
        if (getUi().dialog === "help") updateUi({ dialog: null });
      }}
    >
      <form method="dialog">
        <div className="dialog-title">
          <h2>Working with a trace</h2>
          <button className="icon-button" aria-label="Close help">
            ×
          </button>
        </div>
      </form>
      <div className="help-grid">
        <div>
          <h3>Navigate</h3>
          <p>
            Drag on a timeline or overview to zoom. Shift-drag pans. Double-click a call to fit its
            interval. Click a call for its context; right-click for actions.
          </p>
          <p>
            <kbd>+</kbd> / <kbd>−</kbd> Zoom · <kbd>Home</kbd> Fit trace
            <br />
            <kbd>Alt ←</kbd> / <kbd>Alt →</kbd> Range history
            <br />
            <kbd>B</kbd> Bookmark · <kbd>Esc</kbd> Close context
          </p>
        </div>
        <div>
          <h3>Understand the numbers</h3>
          <p>
            Inclusive time includes nested calls. Exclusive time counts only the active leaf. Both
            are clipped exactly to the selected interval. Calls counts entries inside the interval;
            overlapping counts all intersecting calls.
          </p>
          <p>
            MPI transfer time is the recorded send-to-receive interval. It is not a measurement of
            network latency. Unmatched messages are retained and marked.
          </p>
          <p>
            Sampled call paths are estimates, not measured invocations. Counter rate uses adjacent
            samples and the trace clock.
          </p>
        </div>
      </div>
      <p className="muted">
        Browser interface with a local OTF2 C reader and SQLite index. See README.md and
        docs/coverage.md for supported analyses and known limitations.
      </p>
    </Dialog>
  );
}
