import Brush from "./Brush";
import Toast from "./Toast";
import Tooltip from "./Tooltip";
import HelpDialog from "./dialogs/HelpDialog";
import LoadingDialog from "./dialogs/LoadingDialog";
import OpenTraceDialog from "./dialogs/OpenTraceDialog";
import { useDocumentAttributes } from "./hooks/useDocumentAttributes";
import { useGlobalEvents } from "./hooks/useGlobalEvents";
import ContextMenu from "./layout/ContextMenu";
import Header from "./layout/Header";
import Inspector from "./layout/Inspector";
import Explorer from "./layout/Sidebar/Explorer";
import Workspace from "./layout/Workspace";
import DockingLayer from "./workspace/DockingLayer";

export default function App() {
  useDocumentAttributes();
  useGlobalEvents();
  return (
    <>
      <Header />
      <div className="app-shell">
        <Explorer />
        <Workspace />
      </div>
      <Inspector />
      <Tooltip />
      <Brush />
      <ContextMenu />
      <Toast />
      <OpenTraceDialog />
      <LoadingDialog />
      <HelpDialog />
      <DockingLayer />
    </>
  );
}
