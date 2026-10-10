import { scope } from "../../api/client";
import { QueryView } from "../../components/query/QueryView";
import { useViewState } from "../../hooks/useViewState";
import { Card } from "../../components/panel/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import type { CounterResponse } from "../../api/types/execution";
import { CounterPanel } from "./CounterPanel";

export function CountersView() {
  const state = useViewState();
  if (!state.meta.metrics.length)
    return (
      <QueryView
        queryKey={[state.epoch]}
        load={() => Promise.resolve({})}
        render={() => (
          <Card title="Counter data">
            <EmptyState
              title="No counters were recorded"
              detail="This archive contains no metric definitions."
            />
          </Card>
        )}
      />
    );
  return (
    <QueryView<CounterResponse>
      endpoint={state.counterDerived ? "derived" : "counters"}
      params={scope(
        {
          metric: state.metric,
          metricY: state.metricY,
          mode: state.counterMode,
          expression: state.expression,
          bins: 900,
        },
        state,
      )}
      render={(result) => <CounterPanel result={result} state={state} />}
    />
  );
}
