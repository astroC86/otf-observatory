import { query } from "../../api/client";
import { QueryView } from "../../components/query/QueryView";
import { useViewState } from "../../hooks/useViewState";
import type { DefinitionsResponse } from "../../api/types/data";
import { TracePanel } from "./TracePanel";

export function TraceView() {
  const snapshot = useViewState();
  return (
    <QueryView<DefinitionsResponse | null>
      queryKey={[snapshot.epoch]}
      load={async (signal) =>
        snapshot.traceMode === "definitions"
          ? query<DefinitionsResponse>(
              "definitions",
              {
                kind: snapshot.definitionKind,
                search: snapshot.definitionSearch,
                offset: snapshot.definitionOffset || 0,
              },
              signal,
              snapshot,
            )
          : null
      }
      render={(definitions) => <TracePanel definitions={definitions} snapshot={snapshot} />}
    />
  );
}
