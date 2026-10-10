import { scope } from "../../api/client";
import { QueryView } from "../../components/query/QueryView";
import { useViewState } from "../../hooks/useViewState";
import type { CallTreeRow } from "../../api/types/execution";
import { CallTreePanel } from "./CallTreePanel";

export function CalltreeView() {
  const state = useViewState();
  return (
    <QueryView<readonly CallTreeRow[]>
      endpoint="calltree"
      params={scope({}, state)}
      render={(rows) => <CallTreePanel rows={rows} mode={state.callMode} />}
    />
  );
}
