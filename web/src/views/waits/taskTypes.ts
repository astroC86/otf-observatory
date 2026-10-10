import type { Identity, RelationshipRecord } from "../dependencies/types";
import type { Operation } from "./types";

export interface TaskAnalysis {
  dataflow?: string;
  dataflowReason?: string;
}
export interface TaskCandidate {
  task?: unknown;
  createLocation?: Identity | null;
  createTime?: number;
  completionLocation?: Identity | null;
  completionTime?: number;
  status?: string;
  required?: boolean;
  parentConfidence?: string;
  taskGroup?: boolean;
  source?: Operation;
  target?: Operation;
}
export interface TaskWaitRecord extends RelationshipRecord {
  data?: {
    awaitedTasks?: TaskCandidate[];
    memberTasks?: TaskCandidate[];
    candidateTasks?: TaskCandidate[];
    interpretation?: string;
    recordingContract?: { completionOnly?: boolean };
    waitSemantics?: string;
    waitingTaskInstance?: string;
    candidateCount?: number;
    candidateTotal?: number;
    candidateSetTruncated?: boolean;
    requiredTaskCount?: number;
  };
}
export function taskIdentity(task: unknown): string {
  return Array.isArray(task) ? task.join(" / ") : String(task ?? "Unresolved");
}
