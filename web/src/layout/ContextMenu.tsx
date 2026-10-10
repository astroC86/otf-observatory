import { ControlBar } from "../components/controls/ControlBar";
import { contextAction } from "../state/inspection";
import { exportData } from "../state/exports";
import { useUi } from "../state/useUi";
import { buttonControl } from "../components/controls/factories";

const exports = [
  ["csv", "Export displayed data · CSV"],
  ["json", "Export displayed data · JSON"],
  ["png", "Export first chart · PNG"],
  ["session", "Export session · JSON"],
] as const;
const actions = [
  ["context", "Inspect call"],
  ["zoom", "Zoom to interval"],
  ["function", "Isolate function"],
  ["location", "Isolate location"],
  ["bookmark", "Bookmark interval"],
] as const;

export default function ContextMenu() {
  const { menu } = useUi(({ menu }) => ({ menu }));
  return (
    <div
      id="context-menu"
      className="context-menu"
      hidden={!menu}
      style={menu ? { left: menu.left, top: menu.top } : undefined}
    >
      {menu?.export ? (
        <ControlBar
          className={null}
          controls={exports.map(([kind, children]) =>
            buttonControl(`export-${kind}`, children, () => exportData(kind)),
          )}
        />
      ) : menu ? (
        <ControlBar
          className={null}
          controls={actions.map(([action, children]) => ({
            kind: "button",
            data: { action },
            children,
            onClick: () => {
              if (menu.row) contextAction(action, menu.row);
            },
          }))}
        />
      ) : null}
    </div>
  );
}
