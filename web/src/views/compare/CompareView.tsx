import { queryKeys } from "../../api/queryKeys";
import { QueryView } from "../../components/query/QueryView";
import { useViewState } from "../../hooks/useViewState";
import { CrossRunPanel } from "./CrossRunPanel";
import { MarkerPanel } from "./MarkerPanel";
import { ComparisonResults } from "./ComparisonResults";
import { loadComparison } from "./requests";

export function CompareView() {
  const snapshot = useViewState();
  return (
    <QueryView
      load={(signal) => loadComparison(snapshot, signal)}
      queryKey={queryKeys.view(snapshot)}
      render={(data) => (
        <>
          <CrossRunPanel data={data} snapshot={snapshot} />
          <MarkerPanel data={data} snapshot={snapshot} />
          <ComparisonResults data={data} snapshot={snapshot} />
        </>
      )}
    />
  );
}
