import type { JsonObject, JsonValue } from "../../api/types/common";
import type { LineChartSeries } from "../../charts/types";
import type { DiagnosticData } from "../dependencies/types";

export interface MetricSource extends JsonObject {
  type: string;
}
export interface MetricProgram extends JsonObject {
  name: string;
  unit: string;
  sources: Record<string, MetricSource>;
  expression: string;
  aggregation: string;
  scope: string;
  reduction: string;
}
export type MetricLibrary = Record<string, MetricProgram>;
export interface SourceDraft {
  variable: string;
  source: MetricSource;
  fields: Record<string, string>;
  extra: string;
}
export interface MetricDraft {
  program: MetricProgram;
  sources: SourceDraft[];
}
export interface MetricSeries extends LineChartSeries {
  min: number | null;
  max: number | null;
  samples: number;
  validSamples: number;
  missingSamples: number;
  summary: { operation: string; value: number | null };
}
export interface MetricPixel {
  start: number;
  end: number;
  mean: number | null;
  min: number | null;
  max: number | null;
  sum: number | null;
  contributors: number;
  rawSamples: number;
  attribution58: JsonValue;
  attribution70: JsonValue;
}
export interface PixelDetails {
  timelines: {
    stage: string;
    name?: string;
    location: string;
    operation: string;
    pixels: MetricPixel[];
  }[];
  sources: JsonValue;
}
export interface MetricResult extends DiagnosticData {
  metric: { name: string; unit: string };
  unit?: string;
  series: MetricSeries[];
  pixelDetails?: PixelDetails;
}
export interface MetricPreset {
  id: string;
  name: string;
  available: boolean;
  reason?: string;
  notes?: string[];
  program: Partial<
    Pick<
      MetricProgram,
      "name" | "unit" | "sources" | "expression" | "aggregation" | "scope" | "reduction"
    >
  >;
}
export interface MetricAttribute {
  id: string | number;
  name: string;
  kind: string;
}
export type Evaluation =
  { status: "ready"; result: MetricResult } | { status: "error"; message: string };
export interface StudioData {
  evaluation: Evaluation;
  presets: MetricPreset[];
  presetError: string;
  attributes: MetricAttribute[];
  attributeError: string;
}
