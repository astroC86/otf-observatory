import type {
  LocationDefinition,
  MetricDefinition,
  OverviewData,
  RegionDefinition,
  Rows,
  TimeRange,
} from "./common";

export interface TimelineRow extends TimeRange {
  id: number;
  location: string;
  region: string;
  depth?: number;
  count?: number;
  incomplete?: number;
}
export interface TimelineResponse extends Rows<TimelineRow> {
  truncated: boolean;
}

export interface FunctionSummaryRow extends RegionDefinition {
  region: string;
  calls: number;
  overlapping: number;
  inclusive: number;
  exclusive: number;
  minimum: number;
  maximum: number;
  estimated: number;
  average: number;
}

export interface CallTreeRow extends Pick<
  FunctionSummaryRow,
  "region" | "name" | "calls" | "inclusive" | "exclusive"
> {
  id: number;
  parent: number;
  depth: number;
  overlapping?: number;
}

export interface ProcessSummaryRow extends LocationDefinition {
  exclusive: number;
  groups: Readonly<Record<string, number>>;
  utilization: number;
}

export interface CounterSeries {
  location: string;
  points: readonly (readonly [time: number, value: number | null])[];
  min: number | null;
  max: number | null;
  samples: number;
  name?: string;
  interpolation?: string;
}

export interface CounterResponse {
  metric: Readonly<Partial<MetricDefinition>>;
  series: readonly CounterSeries[];
  unit?: string;
}

export interface OverviewResponse extends OverviewData, TimeRange {}
