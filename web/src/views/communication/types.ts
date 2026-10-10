import type { MessagesResponse } from "../../api/types/data";
import type {
  TransferMatrixResponse,
  TransferSummaryResponse,
  TransferTimelineResponse,
} from "../../api/types/transfers";

export interface CommunicationData {
  readonly messages: MessagesResponse;
  readonly summary: PromiseSettledResult<TransferSummaryResponse>;
  readonly matrix: PromiseSettledResult<TransferMatrixResponse>;
  readonly timeline: PromiseSettledResult<TransferTimelineResponse>;
}
