import type { TraceListing } from "../../api/types/common";
import type { ViewState } from "../../state/types";
import type { DiagnosticData } from "../dependencies/types";

type Run = Pick<TraceListing, "id" | "name">;
export type TimeRange = Record<"start" | "end", number>;
export type AnchorPair = Record<"timeA" | "timeB", number> & { label: string };
export interface AnchorMatch extends AnchorPair {
  kind: string;
  residual: number;
  explicit?: boolean;
}
export interface Alignment extends DiagnosticData {
  method: string;
  shift: number;
  scale: number;
  recommendedMode: string;
  matches: AnchorMatch[];
  piecewise: { a: number; b: number }[];
  quality: Record<
    "matched" | "confidence" | "residualMedian" | "residualP95" | "coverageA" | "coverageB",
    number
  > & {
    correspondenceConfidence?: number;
    level: string;
    status: string;
  };
  ambiguities: { rank: number; candidates: AnchorPair[] }[];
}
export interface EnsembleRun extends Run {
  alignment: Alignment;
}
export interface Ensemble extends DiagnosticData {
  baseline: Run & { range: TimeRange };
  runs: EnsembleRun[];
}
export type ComparisonRow = Record<"a" | "b" | "delta" | "callsA" | "callsB", number> & {
  name: string;
  ratio: number | null;
};
export interface ComparisonResult {
  rows: ComparisonRow[];
  rangeA: [number, number];
  rangeB: [number, number];
}
export type ProfileValue = Record<"time" | "delta" | "calls", number>;
export interface ProfilesResult {
  runs: { id: string }[];
  rows: {
    name: string;
    baseline: number;
    baselineCalls: number;
    values: Record<string, ProfileValue>;
  }[];
  durationSemantics: string;
}
export type ProfileRow = { name: string } & Record<string, string | number>;
export interface MarkerInput {
  time: string | number;
  offset: string | number;
  marker?: string | number;
  location?: string;
}
export interface MarkerSession {
  baseline: string;
  method: string;
  target: number | null;
  runs: (Run & { offset: number; time: number; range: TimeRange })[];
  range: TimeRange;
}
export interface MarkerOptions {
  markers: { id: number; name: string; time: number }[];
  total: number;
  truncated: boolean;
}
export interface MarkerRegion extends TimeRange {
  name: string;
  displayStart: number;
  displayEnd: number;
  coalesced?: number;
}
export interface MarkerResult {
  range: TimeRange;
  runs: (Run & {
    offset: number;
    range: TimeRange;
    fullRange: TimeRange;
    location: string | null;
    locations: Run[];
    timeline: { rows: MarkerRegion[] };
  })[];
  rows: { name: string; values: Record<string, ProfileValue> }[];
  durationSemantics: string;
}
export interface ComparisonData {
  archives: TraceListing[];
  result: ComparisonResult | null;
  ensembleResult: ProfilesResult | null;
  queryError: string;
  markerSession: MarkerSession | null;
  markerResult: MarkerResult | null;
  markerError: string;
}
export interface ComparisonProps {
  data: ComparisonData;
  snapshot: ViewState;
}
