import { startTransition, useState } from "react";
import { DataTable } from "../../../components/table/DataTable";
import { ControlBar } from "../../../components/controls/ControlBar";
import { download } from "../../../lib/download";
import { duration } from "../../../lib/format/time";
import { locName } from "../../../state/selectors";
import { setRange } from "../../../state/rangeActions";
import { EvidenceDetail } from "../EvidenceDetail";
import { buttonControl } from "../../../components/controls/factories";
import { EMPTY } from "../types";
import { activityColumns, alternativeColumns, treeColumns } from "./columns";
import { operationName } from "./prepare";
import type { CauseTree } from "./types";

export function UpstreamDetails({ result }: { result: CauseTree }) {
  const [selected, setSelected] = useState(() => result.nodes[0]);
  const context = selected.context;
  return (
    <EvidenceDetail
      heading="Upstream prerequisites"
      body={[
        result.interpretation,
        result.diagnostics?.length ? (
          <p className="analysis-warning">{`Traversal notes: ${result.diagnostics.map((row) => `${row.code} (${row.count})`).join(", ")}`}</p>
        ) : null,
      ]}
      actions={[
        buttonControl("wait-upstream-export", "Export cause tree", () =>
          download("wait-cause-tree.json", JSON.stringify(result, null, 2), "application/json"),
        ),
      ]}
    >
      <DataTable
        id="wait-upstream-tree"
        rows={result.nodes}
        columns={treeColumns}
        onRow={(node) => startTransition(() => setSelected(node))}
        maxHeight={260}
      />
      <h3 id="wait-source-heading">{`Source activity · ${locName(context.location)}`}</h3>
      <p id="wait-source-range">{`${duration(context.start)} → ${duration(context.end)} · ${operationName(selected.cause.source)} enables ${operationName(selected.cause.target)}${context.taskExecution ? `. Enabling task: ${context.taskExecution.task.join(" / ")}. Upstream task links follow this recorded instance; dependencies between different tasks remain unresolved.` : context.taskSchedulingRecorded ? ". Task scheduling is recorded; the enabling task cannot be established." : ""}`}</p>
      <ControlBar
        className="context-actions"
        controls={[
          buttonControl(
            "wait-source-zoom",
            "Show source interval",
            () => setRange(context.start, context.end),
            { disabled: !(context.end > context.start) },
          ),
        ]}
      />
      <DataTable
        key={selected.id}
        id="wait-source-activity"
        rows={context.segments || EMPTY}
        columns={activityColumns}
        maxHeight={280}
      />
      <div id="wait-source-alternatives">
        {selected.alternatives?.length ? (
          <>
            <h3>Conditional or unresolved upstream links</h3>
            <DataTable
              key={selected.id}
              id="wait-source-alternative-table"
              rows={selected.alternatives}
              columns={alternativeColumns}
              maxHeight={230}
            />
          </>
        ) : null}
      </div>
    </EvidenceDetail>
  );
}
