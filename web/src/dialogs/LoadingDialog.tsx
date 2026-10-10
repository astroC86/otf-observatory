import { Dialog } from "../components/ui/Dialog";
import { cancelImport } from "../state/trace/open";
import { getUi, updateUi } from "../state/store";
import { useUi } from "../state/useUi";

export default function LoadingDialog() {
  const { dialog, loadingTitle, loadingPhase, loadingCount } = useUi(
    ({ dialog, loadingTitle, loadingPhase, loadingCount }) => ({
      dialog,
      loadingTitle,
      loadingPhase,
      loadingCount,
    }),
  );
  return (
    <Dialog
      id="loading-dialog"
      open={dialog === "loading"}
      onCancel={(event) => event.preventDefault()}
      onClose={() => {
        if (getUi().dialog === "loading") updateUi({ dialog: null });
      }}
    >
      <div className="loading-orbit" />
      <h2 id="loading-title">{loadingTitle}</h2>
      <p id="loading-phase">{loadingPhase}</p>
      <p id="loading-count" className="mono">
        {loadingCount}
      </p>
      <div className="progress-track">
        <span />
      </div>
      <p className="muted">The index is reused the next time you open this archive.</p>
      <button id="cancel-import" onClick={cancelImport}>
        Cancel import
      </button>
    </Dialog>
  );
}
