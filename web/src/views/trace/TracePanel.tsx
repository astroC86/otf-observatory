import { Card } from "../../components/panel/Card";
import { ControlBar } from "../../components/controls/ControlBar";
import type { ViewState } from "../../state/types";
import type { DefinitionsResponse } from "../../api/types/data";
import { updateQuery } from "../shared/dataControls";
import { DefinitionBrowser } from "./DefinitionBrowser";
import { TraceProperties } from "./TraceProperties";
import { TraceDiagnostics } from "./TraceDiagnostics";
import { buttonControl } from "../../components/controls/factories";

export function TracePanel({
  definitions,
  snapshot,
}: {
  definitions: DefinitionsResponse | null;
  snapshot: ViewState;
}) {
  return (
    <>
      <Card title="Trace archive">
        <ControlBar
          controls={[
            buttonControl(
              "show-properties",
              "Properties",
              () => updateQuery({ traceMode: "properties" }),
              {
                className: snapshot.traceMode === "properties" ? "primary" : "",
              },
            ),
            buttonControl(
              "show-definitions",
              "Definition browser",
              () => updateQuery({ traceMode: "definitions" }),
              {
                className: snapshot.traceMode === "definitions" ? "primary" : "",
              },
            ),
          ]}
        />
        {definitions ? (
          <DefinitionBrowser definitions={definitions} snapshot={snapshot} />
        ) : (
          <TraceProperties meta={snapshot.meta} />
        )}
      </Card>
      {!definitions ? <TraceDiagnostics meta={snapshot.meta} /> : null}
    </>
  );
}
