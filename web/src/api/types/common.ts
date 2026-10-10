// DTOs describe consumed fields; response objects retain all backend fields for inspection/export.
export type JsonValue = string | number | boolean | null | JsonValue[] | JsonObject;
export type JsonObject = { [key: string]: JsonValue };
export type ApiParams = Record<string, string | number | boolean | null | undefined>;

export interface TimeRange {
  start: number;
  end: number;
}
export interface Rows<Row> {
  readonly rows: readonly Row[];
}
export interface Page<Row> extends Rows<Row> {
  readonly total: number;
}
interface NamedDefinition {
  id: string;
  name: string;
}
export interface RegionDefinition extends NamedDefinition {
  group: string;
  file?: string;
  line?: number;
}
export interface LocationDefinition extends NamedDefinition {
  type: string;
  group: string;
  events: number;
}
export interface GroupDefinition extends NamedDefinition {
  type: string;
  parent: string;
}
export interface SystemNode extends NamedDefinition {
  className: string;
  parent: string;
}
export interface MetricDefinition extends NamedDefinition {
  unit: string;
  description?: string;
}
export interface TraceMeta {
  path: string;
  name: string;
  format: string;
  duration: number;
  importSeconds: number;
  clock: { resolution: number; offset: number };
  counts: Record<string, number> & Record<"events" | "spans" | "messages" | "metrics", number>;
  warnings: Record<string, number>;
  eventTypes: Record<string, number>;
  regions: RegionDefinition[];
  locations: LocationDefinition[];
  groups: GroupDefinition[];
  metrics: MetricDefinition[];
  nodes: SystemNode[];
  files: Record<string, string>;
  [key: string]: unknown;
}
export interface TraceListing extends NamedDefinition {
  path: string;
  format: string;
  loaded: boolean;
}
export interface ImportJob {
  id: string;
  state: string;
  phase: string;
  events?: number;
  error?: string;
}
export interface OverviewData {
  readonly series: Readonly<Record<string, readonly number[]>>;
  readonly bins: number;
}
export interface Bookmark extends TimeRange {
  name: string;
  locations: string[];
}
export type MessageFilter = Partial<Record<"tag" | "comm" | "minBytes" | "status", string>>;
export interface SpanResponse extends TimeRange {
  region: string;
  location: string;
  exclusive: number;
  depth: number;
  path: string;
  regionDefinition?: RegionDefinition;
  incomplete?: boolean;
  sampled?: boolean;
  continuation?: boolean;
  events: Array<{ kind: string; time: number; [key: string]: unknown }>;
}
export interface MenuRow extends Partial<
  Pick<SpanResponse, "region" | "location" | "start" | "end">
> {
  id?: number | string;
}
