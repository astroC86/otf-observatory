import { useMemo, type ReactNode } from "react";
import { compact } from "../../lib/format/numbers";
import { inspectObject } from "../../state/inspection";
import { locName } from "../../state/selectors";
import { setView } from "../../state/viewActions";
import { EmptyState } from "../../components/ui/EmptyState";
import { updateState } from "../../state/store";
import type { TraceMeta } from "../../api/types/common";

export function SystemTree({ meta }: { meta: TraceMeta }) {
  const rows = useMemo(() => {
    const children = new Map<string, TraceMeta["nodes"][number][]>();
    for (const node of meta.nodes) {
      const siblings = children.get(node.parent);
      if (siblings) siblings.push(node);
      else children.set(node.parent, [node]);
    }
    const nodeIds = new Set(meta.nodes.map((node) => node.id));
    const seen = new Set<string>();
    const result: ReactNode[] = [];
    function appendNode(node: TraceMeta["nodes"][number], depth: number) {
      if (seen.has(node.id)) return;
      seen.add(node.id);
      result.push(
        <div key={`node:${node.id}`} className="tree-node" style={{ paddingLeft: 18 + depth * 24 }}>
          <span>{`▾`}</span>
          <strong>{`${node.name ?? ""}`}</strong>
          <small>{`${node.className ?? ""} · ${node.id ?? ""}`}</small>
        </div>,
      );
      for (const group of meta.groups.filter((entry) => entry.parent === node.id)) {
        result.push(
          <div
            key={`group:${group.id}`}
            className="tree-node"
            style={{ paddingLeft: 42 + depth * 24 }}
          >
            <span>{`▦`}</span>
            {`${group.name ?? ""}`}
            <small>{`${group.type ?? ""}`}</small>
            <button
              data-system-group={group.id}
              onClick={() => {
                updateState({
                  locations: new Set(
                    meta.locations
                      .filter((entry) => entry.group === group.id)
                      .map((entry) => entry.id),
                  ),
                });

                setView("timeline");
              }}
            >{`Select`}</button>
          </div>,
        );
        for (const location of meta.locations.filter((entry) => entry.group === group.id)) {
          result.push(
            <div
              key={`location:${location.id}`}
              className="tree-node"
              style={{ paddingLeft: 65 + depth * 24 }}
            >
              <i
                className="swatch"
                style={{
                  background: location.type === "METRIC" ? "#b7c3d1" : "#4d91cf",
                }}
              />
              {`${location.name ?? ""}`}
              <small>{`${location.type ?? ""} · ID ${location.id ?? ""} · ${compact(location.events)} events`}</small>
              <button
                data-system-location={location.id}
                onClick={() => inspectObject(locName(location.id), location)}
              >{`Inspect`}</button>
            </div>,
          );
        }
      }
      for (const child of children.get(node.id) || []) appendNode(child, depth + 1);
    }
    for (const node of meta.nodes) if (!nodeIds.has(node.parent)) appendNode(node, 0);
    return result;
  }, [meta]);
  return (
    <div className="system-tree">
      {rows.length ? (
        rows
      ) : (
        <EmptyState
          title="No system hierarchy"
          detail="The producer did not record system tree definitions."
        />
      )}
    </div>
  );
}
