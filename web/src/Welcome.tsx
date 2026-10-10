import { notify } from "./state/uiActions";
import { openDialog } from "./state/trace/open";

export default function Welcome() {
  const open = () =>
    void openDialog().catch((error: unknown) => {
      notify(error instanceof Error ? error.message : String(error));
    });
  return (
    <div className="welcome">
      <span className="welcome-icon">▥</span>
      <h2>Explore your execution.</h2>
      <p>Open an OTF2 / Score-P archive or a legacy OTF trace.</p>
      <button id="welcome-open" className="primary" onClick={open}>
        Open trace archive
      </button>
      <span>Local processing · No network dependencies</span>
    </div>
  );
}
