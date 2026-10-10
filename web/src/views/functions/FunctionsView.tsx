import { scope } from "../../api/client";
import { QueryView } from "../../components/query/QueryView";
import { useViewState } from "../../hooks/useViewState";
import type { FunctionSummaryRow } from "../../api/types/execution";
import { FunctionsPanel } from "./FunctionsPanel";

export function FunctionsView() {
  const state = useViewState();
  return (
    <QueryView<readonly FunctionSummaryRow[]>
      endpoint="summary"
      params={scope({}, state)}
      render={(rows) => <FunctionsPanel rows={rows} state={state} />}
    />
  );
}
