import { scope } from "../../api/client";
import { QueryView } from "../../components/query/QueryView";
import { useViewState } from "../../hooks/useViewState";
import type { MarkersResponse } from "../../api/types/data";
import { MarkersPanel } from "./MarkersPanel";

export function MarkersView() {
  const snapshot = useViewState();
  return (
    <QueryView<MarkersResponse>
      endpoint="markers"
      params={scope({}, snapshot)}
      render={(recorded) => <MarkersPanel recorded={recorded} snapshot={snapshot} />}
    />
  );
}
