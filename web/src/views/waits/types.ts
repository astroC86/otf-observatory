import type { DiagnosticData, Identity, RelationshipRecord } from "../dependencies/types";

export interface Operation {
  routine?: string;
  kind?: string;
  event?: Identity;
  location?: Identity | null;
  start?: number | null;
  end?: number | null;
  eventTime?: number;
}
export interface WaitCause {
  id: Identity;
  source?: Operation;
  target?: Operation;
  dependency?: { start: number; end: number; duration: number };
  confidence?: string;
  reason?: string;
  relation?: string;
  limiting?: boolean;
  wait?: WaitRow;
  analysis?: string;
}
export interface WaitRow extends RelationshipRecord {
  causes?: WaitCause[];
  causeCount?: number;
  prerequisiteStatus?: string;
  unresolvedReason?: string;
  peer?: Identity | null;
  evidence?: { interpretation?: string };
  completionLocation?: Identity | null;
  participantOverlap?: number | null;
  participantOverlapPercent?: number | null;
  participants?: unknown[] | number;
  complete?: boolean;
}
export interface CausalTotals {
  required: number;
  conditional: number;
}
export interface CausePage {
  offset: number;
  total: number;
  more: boolean;
  limit: number;
}
export interface CauseData {
  causes: WaitCause[];
  unresolved: WaitRow[];
  independent: number;
  totals?: CausalTotals;
  pagination?: CausePage;
}
interface LockEvent {
  location?: Identity | null;
  time: number;
}
export interface RmaLock {
  window?: Identity;
  lock?: Identity;
  allTargets?: boolean;
  targetIdentity?: unknown;
  status?: string;
  request?: LockEvent | null;
  grant?: LockEvent | null;
  unresolvedReasons?: string[];
  unavailableSeconds?: number;
  causes?: WaitCause[];
}
export interface SenderCandidate {
  operation?: Operation;
}
export interface MatchedProbe {
  messageId?: Identity | null;
  generation?: number | null;
  status?: string;
  scopeAssumption?: string;
  unresolvedReasons?: string[];
  probe?: Operation;
  receive?: Operation;
  completion?: Operation;
  request?: { id: Identity; generation: number };
  sendCandidates?: SenderCandidate[];
  candidateCount?: number;
  candidateCountComplete?: boolean;
}
export interface WaitResponse extends DiagnosticData {
  rows?: WaitRow[];
  summary?: WaitRow[];
  totals?: {
    observed?: number;
    inferred?: number;
    collectiveCount?: number;
    requestCount?: number;
  };
  total?: number;
  more?: boolean;
  causeTotal?: number;
  causeOffset?: number;
  causeLimit?: number;
  causesMore?: boolean;
  causalTotals?: CausalTotals;
  collectives?: WaitRow[];
  collectiveTotal?: number;
  collectivesMore?: boolean;
  requests?: WaitRow[];
  requestTotal?: number;
  requestsMore?: boolean;
  matchedProbes?: MatchedProbe[];
  matchedProbeTotal?: number;
  matchedProbesMore?: boolean;
  rmaLocks?: RmaLock[];
  rmaLockTotal?: number;
  rmaLocksMore?: boolean;
  rmaLockCausalTotals?: CausalTotals;
}
export const EMPTY: never[] = [];
