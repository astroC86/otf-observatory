import { scope } from "../../api/client";
import { QueryView } from "../../components/query/QueryView";
import { useViewState } from "../../hooks/useViewState";
import { WaitsPanel } from "./WaitsPanel";
import type { WaitResponse } from "./types";

export function WaitsView() {
  const snapshot = useViewState();
  const source = snapshot.waitSource || "waits";
  return (
    <QueryView<WaitResponse>
      endpoint={source}
      params={scope(
        {
          offset: snapshot.waitOffset || 0,
          causeOffset: snapshot.waitCauseOffset || 0,
          causeLimit: 500,
          requestOffset: snapshot.waitRequestOffset || 0,
          collectiveOffset: snapshot.waitCollectiveOffset || 0,
          probeOffset: snapshot.waitProbeOffset || 0,
          rmaLockOffset: snapshot.waitRmaLockOffset || 0,
          limit: 500,
          category: snapshot.waitCategory || "",
        },
        snapshot,
      )}
      render={(data) => <WaitsPanel data={data} snapshot={snapshot} />}
    />
  );
}
