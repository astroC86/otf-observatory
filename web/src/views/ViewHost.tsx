import { memo, Suspense, useDeferredValue, useMemo } from "react";
import { useCommittedView } from "../state/useCommittedView";
import { ViewStateContext } from "./ViewStateContext";
import Welcome from "../Welcome";
import { viewComponents } from "./registry";
import { TimelineView } from "./timeline/TimelineView";
import { ViewErrorBoundary } from "./ViewErrorBoundary";
export const ViewHost = memo(function ViewHost() {
  const snapshot = useDeferredValue(useCommittedView());
  const content = useMemo(() => {
    if (!snapshot) return <Welcome />;
    if (snapshot.view === "workspace") return null;
    const View = viewComponents[snapshot.view] || TimelineView;
    return (
      <ViewStateContext.Provider key={`${snapshot.id}:${snapshot.view}`} value={snapshot}>
        <View />
      </ViewStateContext.Provider>
    );
  }, [snapshot]);
  return (
    <ViewErrorBoundary epoch={snapshot?.epoch ?? 0}>
      <Suspense fallback={<Welcome />}>{content}</Suspense>
    </ViewErrorBoundary>
  );
});
