import { Badge } from "../components/ui/Badge";
import { ControlBar } from "../components/controls/ControlBar";
import type { ControlSpec } from "../components/controls/types";
import { notify, toggleTheme } from "../state/uiActions";
import { openDialog } from "../state/trace/open";
import { saveSession } from "../state/session";
import { updateUi } from "../state/store";
import { useStore } from "../state/useStore";
import { useUi } from "../state/useUi";
import { buttonControl } from "../components/controls/factories";

export default function Header() {
  const { meta } = useStore(({ meta }) => ({ meta }));
  const { theme } = useUi(({ theme }) => ({ theme }));
  const open = () =>
    void openDialog().catch((error: unknown) => {
      notify(error instanceof Error ? error.message : String(error));
    });
  const controls: ControlSpec[] = [
    buttonControl("theme", "◐", toggleTheme, {
      className: "icon-button",
      title: "Switch color theme",
      ariaLabel: "Switch color theme",
      ariaPressed: theme === "dark",
    }),
    buttonControl("help", "?", () => updateUi({ dialog: "help" }), {
      className: "icon-button",
      title: "Keyboard shortcuts and analysis semantics",
      ariaLabel: "Help",
    }),
    buttonControl("save-session", "Save session", saveSession, {
      className: "quiet",
    }),
    buttonControl("open", "＋ Open trace", open, {
      className: "primary",
    }),
  ];
  return (
    <header className="app-header">
      <a className="brand" href="/" aria-label="OTF Observatory home">
        <span className="brand-mark">▥</span>
        <strong>
          OTF<span>OBSERVATORY</span>
        </strong>
      </a>
      <div className="header-divider" />
      <button id="trace-picker" className="trace-picker" title="Open a trace" onClick={open}>
        <span id="trace-name" title={meta?.path}>
          {meta
            ? meta.path.includes("run-396831")
              ? "run-396831 / " + meta.name
              : meta.name
            : "Open a trace archive"}
        </span>
        <span className="chevron">⌄</span>
      </button>
      <Badge id="format-badge">{meta?.format || "LOCAL"}</Badge>
      <div className="header-spacer" />
      <ControlBar className={null} controls={controls} />
    </header>
  );
}
