import { query } from "../../api/client";
import { QueryView } from "../../components/query/QueryView";
import { useViewState } from "../../hooks/useViewState";
import type { MessagesResponse } from "../../api/types/data";
import type {
  TransferMatrixResponse,
  TransferSummaryResponse,
  TransferTimelineResponse,
} from "../../api/types/transfers";
import type { CommunicationData } from "./types";
import { CommunicationPanel } from "./CommunicationPanel";

export function CommunicationView() {
  const snapshot = useViewState();
  return (
    <QueryView<CommunicationData>
      queryKey={[snapshot.epoch]}
      load={async (signal) => {
        const filter = snapshot.messageFilter || {};
        const [messages, summary, matrix, timeline] = await Promise.allSettled([
          query<MessagesResponse>(
            "messages",
            {
              ...filter,
              by: snapshot.messageBy,
              offset: snapshot.messageOffset,
            },
            signal,
            snapshot,
          ),
          query<TransferSummaryResponse>(
            "messages/summary",
            {
              tag: filter.tag || "",
              comm: filter.comm || "",
              minBytes: filter.minBytes || "",
              transferTypes: snapshot.transferSummaryTypes || "",
            },
            signal,
            snapshot,
          ),
          query<TransferMatrixResponse>(
            "messages/matrix",
            {
              tag: filter.tag || "",
              comm: filter.comm || "",
              minBytes: filter.minBytes || "",
              transferTypes: snapshot.transferMatrixTypes || "",
              maxGroups: snapshot.transferMatrixMaxGroups || 32,
            },
            signal,
            snapshot,
          ),
          query<TransferTimelineResponse>(
            "messages/timeline",
            {
              tag: filter.tag || "",
              comm: filter.comm || "",
              minBytes: filter.minBytes || "",
              transferTypes: snapshot.transferTimelineTypes || "",
              bins: snapshot.transferTimelineBins ?? 100,
              metric: snapshot.transferTimelineMetric || "count",
              maxKeys: snapshot.transferTimelineMaxKeys ?? 20,
            },
            signal,
            snapshot,
          ),
        ]);
        if (messages.status === "rejected") throw messages.reason;
        return { messages: messages.value, summary, matrix, timeline };
      }}
      render={(result) => <CommunicationPanel result={result} snapshot={snapshot} />}
    />
  );
}
