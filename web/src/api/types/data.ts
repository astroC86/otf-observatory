import type { Page, Rows } from "./common";

interface OperationInterval {
  readonly location: string;
  readonly start: number;
  readonly end: number | null;
  readonly operation: string;
}
interface OperationResponse<Row, Summary> extends Page<Row> {
  readonly summary: readonly Summary[];
}

export interface MessageRow {
  readonly source: string | null;
  readonly target: string | null;
  readonly start: number | null;
  readonly end: number | null;
  readonly comm: string;
  readonly tag: string;
  readonly bytes: number;
  readonly status: string;
  readonly bandwidth: number | null;
}

export interface MessageMatrixRow extends Omit<MessageHistogramRow, "label"> {
  readonly source: string | null;
  readonly target: string | null;
  readonly matched: number;
}

export interface MessageHistogramRow {
  readonly label: string | number | null;
  readonly count: number;
  readonly bytes: number;
  readonly duration: number | null;
}

export interface MessagesResponse extends Page<MessageRow> {
  readonly matrix: readonly MessageMatrixRow[];
  readonly histogram: readonly MessageHistogramRow[];
}

export interface CollectiveRow extends OperationInterval {
  readonly comm: string;
  readonly root: string | null;
  readonly sent: number;
  readonly received: number;
}

export interface CollectiveSummaryRow extends Omit<ResourceSummaryRow, "file"> {
  readonly received: number;
}

export type CollectivesResponse = OperationResponse<CollectiveRow, CollectiveSummaryRow>;

export interface ResourceOperationRow extends OperationInterval {
  readonly bytes: number;
  readonly status: string;
  readonly file?: string;
  readonly win?: string;
}

export interface ResourceSummaryRow {
  readonly operation: string;
  readonly count: number;
  readonly duration: number;
  readonly bytes: number;
  readonly file?: string;
}

export type ResourceResponse = OperationResponse<ResourceOperationRow, ResourceSummaryRow>;

export interface EventRow {
  readonly id: number;
  readonly location: string;
  readonly time: number;
  readonly tick: string;
  readonly kind: string;
  readonly data: Readonly<Record<string, unknown>>;
}

export interface EventsResponse extends Rows<EventRow> {
  readonly more: boolean;
}

export interface MarkerRow {
  readonly time: number;
  readonly duration: number | null;
  readonly name: string;
  readonly category: string;
  readonly severity: string;
}

export type MarkersResponse = readonly MarkerRow[];

export interface DefinitionRow {
  readonly kind: string;
  readonly id: string;
  readonly data: Readonly<Record<string, unknown>>;
}

export interface DefinitionsResponse extends Page<DefinitionRow> {
  readonly kinds: readonly string[];
}

export interface EventTypeCountRow {
  readonly kind: string;
  readonly count: number;
}
