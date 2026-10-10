import { scope } from "../../api/client";
import { QueryView } from "../../components/query/QueryView";
import { useViewState } from "../../hooks/useViewState";
import type { DefinitionsResponse } from "../../api/types/data";
import { SystemPanel } from "./SystemPanel";

export function SystemView() {
  const snapshot = useViewState();
  return (
    <QueryView<DefinitionsResponse>
      endpoint="definitions"
      params={scope({ kind: "CartTopology" }, snapshot)}
      render={(definitions) => <SystemPanel meta={snapshot.meta} definitions={definitions} />}
    />
  );
}
