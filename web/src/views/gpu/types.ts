import type { Identity, RelationshipRecord } from "../dependencies/types";

export interface ClockLocation {
  location: Identity;
  status: string;
  samples?: readonly unknown[];
  intervals?: readonly unknown[];
}

export interface ClockProvenance {
  correctionsApplied?: boolean;
  eventTimeDomain: string;
  interpolation: string;
  uncertainty: string;
  locations?: ClockLocation[];
}

export interface GpuDevice extends RelationshipRecord {
  bytes?: number;
  utilization?: number | null;
}

export interface ExternalRecord extends RelationshipRecord {
  recordType?: string;
  domain?: string;
}

export interface ExternalMapping {
  externalKindName?: string;
  externalKind: string;
  externalId: Identity;
  correlationId: Identity;
  status: string;
  time: number;
  location: Identity;
  partial?: boolean;
  externalRecords?: ExternalRecord[];
  internalRecords?: ExternalRecord[];
  externalRecordTotal?: number;
  internalRecordTotal?: number;
}

export type IdleLevel = "devices" | "contexts" | "locations";
export type IdleMode = 0 | 1 | 2;

export interface IdleRow {
  key: readonly Identity[];
  name?: string;
  location?: Identity;
  locations?: readonly Identity[];
  duration: number;
  active: number;
  idle: number;
  idlePercentage: number | null;
}

export interface NamedIdleRow extends IdleRow {
  name: string;
  members: number;
}

export interface IdleData {
  devices: IdleRow[];
  contexts: IdleRow[];
  locations: IdleRow[];
  source: string;
  start: number;
  end: number;
  eventMode: IdleMode;
  sessionProducer: string;
  diagnostics: { code: string; count: number }[];
}

export type IdleResult = PromiseSettledResult<IdleData>;
