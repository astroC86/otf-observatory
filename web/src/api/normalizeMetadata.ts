import type { TraceMeta } from "./types/common";

// Synthetic and older indexes can omit empty definition/diagnostic collections.
// Preserve every supplied field; only absent collections receive empty values.
export function normalizeMetadata(value: unknown): TraceMeta {
  const meta = value as TraceMeta;
  return {
    ...meta,
    eventTypes: meta.eventTypes ?? {},
    warnings: meta.warnings ?? {},
    files: meta.files ?? {},
    regions: meta.regions ?? [],
    locations: meta.locations ?? [],
    groups: meta.groups ?? [],
    metrics: meta.metrics ?? [],
    nodes: meta.nodes ?? [],
  };
}
