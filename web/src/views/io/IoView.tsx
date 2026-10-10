import { scope } from "../../api/client";
import { QueryView } from "../../components/query/QueryView";
import { useViewState } from "../../hooks/useViewState";
import type { ResourceResponse } from "../../api/types/data";
import { IoPanel } from "./IoPanel";

export function IoView() {
  const snapshot = useViewState();
  return (
    <QueryView<ResourceResponse>
      endpoint={snapshot.ioMode}
      params={scope({}, snapshot)}
      render={(data) => <IoPanel data={data} snapshot={snapshot} />}
    />
  );
}
