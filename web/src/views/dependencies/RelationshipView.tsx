import { api, query, scope } from "../../api/client";
import { QueryView } from "../../components/query/QueryView";
import { useViewState } from "../../hooks/useViewState";
import type { IdleData } from "../gpu/types";
import { RelationshipPanel } from "./RelationshipPanel";
import type { RelationshipData, RelationshipResult } from "./types";

export function RelationshipView() {
  const snapshot = useViewState();
  const kind = snapshot.view === "gpu" ? "gpu" : "dependencies";
  const params = scope(
    {
      limit: 5000,
      scanLimit: 250000,
      offset: snapshot.relationshipOffset,
      ...(kind === "gpu"
        ? {
            externalMappingOffset: snapshot.gpuExternalOffset,
            externalMappingLimit: 500,
          }
        : {}),
      kind: snapshot.relationshipKind[kind] || "",
      search: snapshot.relationshipSearch,
    },
    snapshot,
  );
  return (
    <QueryView<RelationshipResult>
      queryKey={[kind, params, snapshot.gpuIdleEventMode]}
      load={async (signal) => {
        const records = api<RelationshipData>(kind, params, undefined, signal);
        if (kind === "dependencies") return { kind, data: await records };
        const [data, idle] = await Promise.allSettled([
          records,
          query<IdleData>(
            "gpu/idle",
            {
              eventMode: snapshot.gpuIdleEventMode,
            },
            signal,
            snapshot,
          ),
        ]);
        if (data.status === "rejected") throw data.reason;
        return { kind, data: data.value, idle };
      }}
      render={(result) => <RelationshipPanel result={result} snapshot={snapshot} />}
    />
  );
}
