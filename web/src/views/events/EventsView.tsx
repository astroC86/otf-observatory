import { scope } from "../../api/client";
import { QueryView } from "../../components/query/QueryView";
import { useViewState } from "../../hooks/useViewState";
import type { EventsResponse } from "../../api/types/data";
import { EventsPanel } from "./EventsPanel";

export function EventsView() {
  const snapshot = useViewState();
  return (
    <QueryView<EventsResponse>
      endpoint="events"
      params={scope(
        {
          kind: snapshot.eventKind,
          search: snapshot.eventSearch,
          offset: snapshot.eventOffset,
        },
        snapshot,
      )}
      render={(data) => <EventsPanel data={data} snapshot={snapshot} />}
    />
  );
}
