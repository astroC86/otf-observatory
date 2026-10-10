// These order imperative open/restore/embed commands, not React query results.
let traceLoadRequest = 0;
let loadingId: string | null = null;
export function beginTraceLoad(): number {
  return ++traceLoadRequest;
}
export function currentTraceLoad(): number {
  return traceLoadRequest;
}
export function isCurrentTraceLoad(candidate: number): boolean {
  return candidate === traceLoadRequest;
}
export function getLoadingId(): string | null {
  return loadingId;
}
export function setLoadingId(id: string): void {
  loadingId = id;
}
