import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, scope } from "../../../api/client";
import type { ApiParams } from "../../../api/types/common";
import { ControlBar } from "../../../components/controls/ControlBar";
import { buttonControl } from "../../../components/controls/factories";
import { duration } from "../../../lib/format/time";
import { locName } from "../../../state/selectors";
import { setRange } from "../../../state/rangeActions";
import { EvidenceDetail } from "../EvidenceDetail";
import { hasOperationRange, rangeAction } from "../detailActions";
import type { WaitCause } from "../types";
import { operationName } from "./prepare";
import { UpstreamDetails } from "./UpstreamDetails";
import type { CauseTree } from "./types";

export function CauseDetail({ cause }: { cause: WaitCause }) {
  const instance = useId();
  const [request, setRequest] = useState<{ attempt: number; params: ApiParams }>(() => ({
    attempt: 0,
    params: {},
  }));
  const result = useQuery({
    queryKey: ["wait-cause", instance, request.attempt, request.params],
    queryFn: ({ signal }) => api<CauseTree>("wait-cause", request.params, undefined, signal),
    enabled: request.attempt > 0,
    retry: false,
  });
  const source = cause.source,
    target = cause.target || cause.wait,
    dependency = cause.dependency;
  const pair = hasOperationRange(source) && hasOperationRange(target);
  function load() {
    const params = scope({
      analysis: cause.analysis || "waits",
      cause: cause.id,
      start: dependency?.start,
      end: dependency?.end,
    });
    setRequest((previous) => ({ attempt: previous.attempt + 1, params }));
  }
  return (
    <div className="wait-cause-detail">
      <EvidenceDetail
        heading={`${operationName(source)} → ${operationName(target)}`}
        body={[
          <p>
            <strong>Enabling operation:</strong>
            {` ${locName(source?.location)} · ${duration(source?.start)} → ${duration(source?.end)}`}
          </p>,
          <p>
            <strong>Affected operation:</strong>
            {` ${locName(target?.location)} · ${duration(target?.start)} → ${duration(target?.end)}`}
          </p>,
          <p>
            <strong>Dependency delay:</strong>
            {` ${duration(dependency?.duration)} (${duration(dependency?.start)} → ${duration(dependency?.end)})`}
          </p>,
          `${cause.confidence || ""} · ${cause.reason || cause.relation || ""}`,
        ]}
        actions={[
          rangeAction("wait-show-cause", "Show enabling operation", source),
          rangeAction("wait-show-target", "Show affected operation", target),
          buttonControl(
            "wait-show-pair",
            "Show both operations",
            () => {
              if (pair)
                setRange(Math.min(source.start, target.start), Math.max(source.end, target.end));
            },
            { disabled: !pair },
          ),
        ]}
      />
      <ControlBar
        className="context-actions"
        controls={[
          buttonControl("wait-upstream-load", "Trace upstream causes", load, {
            disabled: request.attempt > 0 && !result.isError,
          }),
        ]}
      />
      <div id="wait-upstream-content" aria-live="polite">
        {request.attempt ? (
          result.isSuccess ? (
            <UpstreamDetails result={result.data} />
          ) : result.isError ? (
            result.error.message
          ) : (
            "Reading source activity and upstream prerequisites…"
          )
        ) : null}
      </div>
    </div>
  );
}
