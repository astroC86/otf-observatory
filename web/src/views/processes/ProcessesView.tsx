import { scope } from "../../api/client";
import { QueryView } from "../../components/query/QueryView";
import { useViewState } from "../../hooks/useViewState";
import type { ProcessSummaryRow } from "../../api/types/execution";
import { ProcessesPanel } from "./ProcessesPanel";

export function ProcessesView() {
  const state = useViewState();
  return (
    <QueryView<readonly ProcessSummaryRow[]>
      endpoint="processes"
      params={scope({}, state)}
      render={(rows) => <ProcessesPanel all={rows} />}
    />
  );
}
