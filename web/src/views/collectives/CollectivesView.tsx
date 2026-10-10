import { scope } from "../../api/client";
import { QueryView } from "../../components/query/QueryView";
import { useViewState } from "../../hooks/useViewState";
import type { CollectivesResponse } from "../../api/types/data";
import { CollectivesPanel } from "./CollectivesPanel";

export function CollectivesView() {
  const snapshot = useViewState();
  return (
    <QueryView<CollectivesResponse>
      endpoint="collectives"
      params={scope({}, snapshot)}
      render={(data) => <CollectivesPanel data={data} />}
    />
  );
}
