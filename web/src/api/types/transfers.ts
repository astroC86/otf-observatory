import type { TimeRange } from "./common";

export interface TransferExtrema {
  readonly minimum: number;
  readonly maximum: number;
}

export interface TransferScalar extends TransferExtrema {
  readonly sum: number;
  readonly count: number;
}

export interface TransferStatistics {
  readonly count: number;
  readonly duration: TransferScalar;
  readonly bytes: TransferScalar;
  readonly rate: TransferExtrema;
}

export type TransferTotals = TransferStatistics | Readonly<{ count: 0 }>;
export type TransferGroup = "size" | "tag" | "type" | "communicator" | "callsite";
export type TransferKey = string | number;

export interface TransferGroupRow extends TransferStatistics {
  readonly key: TransferKey;
}

interface TransferWindowResponse extends Readonly<TimeRange> {
  readonly clockResolution: string;
  readonly totals: TransferTotals;
  readonly diagnostics: readonly Readonly<{ code: string; count: number }>[];
  readonly semantics: Readonly<Record<string, string>>;
}

type TransferGroups<Row> = Readonly<Record<TransferGroup, readonly Row[]>>;

export interface TransferSummaryResponse extends TransferWindowResponse {
  readonly groups: TransferGroups<TransferGroupRow>;
  readonly callsites: Readonly<Record<string, Readonly<Record<string, unknown>>>>;
}

export interface TransferMatrixCell extends TransferStatistics {
  readonly source: string;
  readonly target: string;
  readonly values: Readonly<Record<string, number>>;
}

export interface TransferLocationGroup {
  readonly id: string;
  readonly name?: string;
}

export interface TransferMatrixResponse extends TransferWindowResponse {
  readonly cells: readonly TransferMatrixCell[];
  readonly senderGroups: readonly TransferLocationGroup[];
  readonly receiverGroups: readonly TransferLocationGroup[];
  readonly locationPairs: number;
  readonly locationSummary: readonly Readonly<Record<string, unknown>>[];
  readonly grouping: Readonly<Record<string, unknown>>;
}

export interface TransferTimelineDisplayRow {
  readonly key: TransferKey;
  readonly value: number;
  readonly other?: boolean;
}
interface TransferKeyReduction {
  readonly originalKeyCount: number;
  readonly retainedKeyCount: number;
  readonly triggered: boolean;
}

export interface TransferTimelineResponse extends TransferWindowResponse {
  readonly binBounds: readonly number[];
  readonly binTotals: readonly TransferTotals[];
  readonly binRecordCount: number;
  readonly boundaryDuplicateCount: number;
  readonly groups: TransferGroups<readonly TransferGroupRow[]>;
  readonly displayGroups: TransferGroups<readonly TransferTimelineDisplayRow[]>;
  readonly keyReduction: Readonly<Record<TransferGroup, TransferKeyReduction>>;
  readonly callsites: TransferSummaryResponse["callsites"];
}
