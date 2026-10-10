import type { ClockProvenance, ExternalMapping, GpuDevice, IdleResult } from "../gpu/types";

export type Identity = string | number;
export type RelationshipResult =
  | { kind: "dependencies"; data: RelationshipData }
  | { kind: "gpu"; data: RelationshipData; idle: IdleResult };

export interface RelationshipRecord {
  [key: string]: unknown;
  id?: Identity;
  event?: Identity;
  kind?: string;
  category?: string;
  label?: string;
  routine?: string;
  location?: Identity | null;
  start?: number | null;
  end?: number | null;
  time?: number | null;
  status?: string;
  confidence?: string;
  source?: Identity;
  target?: Identity;
  evidence?: readonly Identity[] | object;
  observed?: number;
  inferred?: number;
  causes?: readonly {
    relation?: string;
    dependency?: { start: number; end: number; duration: number } | null;
  }[];
}

export interface AnalysisNote {
  code?: string;
  count?: number;
  message?: string;
}

export interface SourceDiagnostic {
  source: string;
  location: Identity;
  kind: string;
  skipped?: Readonly<Record<string, number>>;
  uncertain?: Readonly<Record<string, number>>;
  extensions?: Readonly<Record<string, number>>;
}

export interface DiagnosticData {
  truncated?: boolean;
  diagnostics?: readonly (AnalysisNote | string)[];
  sourceDiagnostics?: readonly SourceDiagnostic[];
}

export interface RelationshipData extends DiagnosticData {
  intervals?: RelationshipRecord[];
  nodes?: RelationshipRecord[];
  edges?: RelationshipRecord[];
  availableKinds?: string[];
  timelineIntervals?: RelationshipRecord[];
  timelineEdges?: RelationshipRecord[];
  intervalTotal?: number;
  edgeTotal?: number;
  more?: boolean;
  scannedEvents?: number;
  displayReduction?: string;
  summary?: {
    kernels?: number;
    copies?: number;
    intervals?: number;
    edges?: number;
    devices?: GpuDevice[] | Record<string, GpuDevice>;
  };
  threadLockAnalysis?: { required: number; conditional: number };
  taskAnalysis?: Record<string, unknown>;
  clockProvenance?: ClockProvenance;
  devices?: GpuDevice[] | Record<string, GpuDevice>;
  correlationCandidateTotal?: number;
  correlationCandidates?: RelationshipRecord[];
  externalMappingTotal?: number;
  externalMappingInvalidRecords?: number;
  externalMappingPartial?: boolean;
  externalMappingOffset?: number;
  externalMappingMore?: boolean;
  externalMappings?: ExternalMapping[];
}

export const EMPTY_RECORDS: readonly RelationshipRecord[] = [];
