import { useRef, useState } from "react";
import { Badge } from "../components/ui/Badge";
import { ControlBar } from "../components/controls/ControlBar";
import { Dialog } from "../components/ui/Dialog";
import { openTrace } from "../state/trace/open";
import { restoreSession } from "../state/session";
import { uploadFolder } from "../state/trace/upload";
import { getUi, updateUi } from "../state/store";
import { useUi } from "../state/useUi";
import { buttonControl } from "../components/controls/factories";

const directoryAttributes = { webkitdirectory: "" };

export default function OpenTraceDialog() {
  const { dialog, openError, traces } = useUi(({ dialog, openError, traces }) => ({
    dialog,
    openError,
    traces,
  }));
  const [path, setPath] = useState("");
  const folderInput = useRef<HTMLInputElement>(null);
  const sessionInput = useRef<HTMLInputElement>(null);
  const openPath = () => void openTrace({ path });
  return (
    <Dialog
      id="open-dialog"
      open={dialog === "open"}
      onClose={() => {
        if (getUi().dialog === "open") updateUi({ dialog: null });
      }}
    >
      <form method="dialog">
        <div className="dialog-title">
          <div>
            <div className="eyebrow">TRACE ARCHIVES</div>
            <h2>Open a trace</h2>
          </div>
          <button className="icon-button" aria-label="Close dialog">
            ×
          </button>
        </div>
      </form>
      <p className="muted">
        Select the anchor file. Its definitions and event streams must remain alongside it.
      </p>
      <div id="trace-list" className="trace-list">
        {traces.map((trace) => (
          <button
            key={trace.id}
            className="trace-item"
            data-trace={trace.id}
            title={`${trace.name}\n${trace.path}`}
            onClick={() => void openTrace({ id: trace.id })}
          >
            <span className="file-icon" aria-hidden="true">
              ▥
            </span>
            <div>
              <strong title={trace.name}>{trace.name}</strong>
              <small title={trace.path}>{trace.path}</small>
            </div>
            <Badge>{`${trace.format}${trace.loaded ? " · READY" : ""}`}</Badge>
          </button>
        ))}
      </div>
      <div className="path-open">
        <label htmlFor="trace-path">Local archive path</label>
        <div>
          <input
            id="trace-path"
            placeholder="/path/to/traces.otf2"
            autoComplete="off"
            value={path}
            onChange={(event) => setPath(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") openPath();
            }}
          />
          <button id="open-path" className="primary" onClick={openPath}>
            Open
          </button>
        </div>
      </div>
      <ControlBar
        className="dialog-bottom"
        controls={[
          buttonControl("upload-folder", "↑ Import trace folder", () =>
            folderInput.current?.click(),
          ),
          buttonControl("load-session", "Restore session", () => sessionInput.current?.click()),
          {
            kind: "content",
            key: "formats",
            children: <span className="muted">OTF2 · OTF</span>,
          },
        ]}
      />
      <input
        id="folder-input"
        ref={folderInput}
        type="file"
        {...directoryAttributes}
        multiple
        hidden
        onChange={uploadFolder}
      />
      <input
        id="session-input"
        ref={sessionInput}
        type="file"
        accept=".json"
        hidden
        onChange={restoreSession}
      />
      <p id="open-error" className="error" hidden={!openError}>
        {openError}
      </p>
    </Dialog>
  );
}
