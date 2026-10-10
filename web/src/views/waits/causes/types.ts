import type { Identity } from "../../dependencies/types";
import type { Operation, WaitCause } from "../types";

export interface ActivitySegment {
  start: number;
  end: number;
  duration: number;
  operations?: Operation[];
  operationCount: number;
  status: string;
}

export interface UpstreamAlternative {
  cause: WaitCause;
  reason: string;
}

export interface UpstreamNode {
  id: number;
  parent: number | null;
  cause: WaitCause;
  context: {
    location: Identity | null;
    start: number;
    end: number;
    taskExecution?: { task: Identity[] };
    taskSchedulingRecorded?: boolean;
    segments?: ActivitySegment[];
  };
  alternatives?: UpstreamAlternative[];
  taskOrder?: {
    task: Identity[];
    predecessorExecution: { location: Identity };
    enablingExecution: { location: Identity };
  };
}

export interface CauseTree {
  interpretation: string;
  diagnostics?: { code: string; count: number }[];
  nodes: [UpstreamNode, ...UpstreamNode[]];
}
