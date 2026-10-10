import type { RelationshipRecord } from "../../dependencies/types";
import type { CauseData, Operation, WaitResponse, WaitRow } from "../types";
import { EMPTY } from "../types";

export function operationName(value: Operation | undefined): string {
  return (
    value?.routine ||
    value?.kind ||
    (value?.event != null ? `Event ${value.event}` : "Unidentified operation")
  );
}
export function prepareCauses(
  rows: readonly WaitRow[],
  data: WaitResponse,
  analysis: string,
): CauseData {
  return {
    causes: rows.flatMap((wait) =>
      (wait.causes || EMPTY).map((cause) => ({ ...cause, wait, analysis })),
    ),
    independent: rows.reduce(
      (count, wait) => count + Number(wait.prerequisiteStatus === "not-required"),
      0,
    ),
    unresolved: rows.filter(
      (wait) =>
        wait.prerequisiteStatus !== "not-required" && !(wait.causeCount ?? wait.causes?.length),
    ),
    totals: data.causalTotals,
    pagination:
      data.causeTotal == null
        ? undefined
        : {
            offset: data.causeOffset || 0,
            total: data.causeTotal,
            more: Boolean(data.causesMore),
            limit: data.causeLimit || 500,
          },
  };
}
export function causeGraph(data: CauseData) {
  const nodes: RelationshipRecord[] = [],
    edges: RelationshipRecord[] = [];
  for (const cause of data.causes) {
    const source = cause.source,
      target = cause.target || cause.wait;
    if (source?.location == null || target?.location == null) continue;
    const a = {
      ...source,
      id: `${cause.id}:source`,
      time: source.start,
      label: operationName(source),
      waitCause: cause,
    };
    const b = {
      ...target,
      id: `${cause.id}:target`,
      time: cause.dependency?.end ?? target.start,
      label: operationName(target),
      waitCause: cause,
    };
    nodes.push(a, b);
    edges.push({
      id: cause.id,
      source: a.id,
      target: b.id,
      confidence: cause.confidence,
      start: a.time,
      end: b.time,
    });
  }
  return { nodes, edges };
}
