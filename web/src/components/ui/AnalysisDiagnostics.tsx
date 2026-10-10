import type { ReactNode } from "react";
import { locName } from "../../state/selectors";
import { num } from "../../lib/format/numbers";
import type { DiagnosticData, SourceDiagnostic } from "../../views/dependencies/types";
import { useEmbedHidden } from "../../embed/useEmbedHidden";

const EMPTY_NOTES: NonNullable<DiagnosticData["diagnostics"]> = [];
const EMPTY_SOURCES: readonly SourceDiagnostic[] = [];
const REASONS = [
  ["Omitted", "skipped"],
  ["Normalization not established", "uncertain"],
  ["Selected extension", "extensions"],
] as const;

export function AnalysisDiagnostics({
  data,
  summary,
  open = false,
}: {
  data: DiagnosticData;
  summary?: ReactNode;
  open?: boolean;
}) {
  const hidden = useEmbedHidden();
  const notes = data.diagnostics ?? EMPTY_NOTES;
  const sources = data.sourceDiagnostics ?? EMPTY_SOURCES;
  return (
    <>
      {data.truncated && (
        <p className="analysis-warning" data-embed-hidden={hidden || undefined}>
          Display or scan limit reached. Narrow the selected time range to inspect additional
          records.
        </p>
      )}
      {notes.length > 0 && (
        <details
          className="analysis-diagnostics"
          data-embed-hidden={hidden || undefined}
          open={open}
        >
          <summary>{summary ?? `${notes.length} analysis notes`}</summary>
          <ul>
            {notes.map((note, index) => {
              const record = typeof note === "string" ? {} : note;
              return (
                <li key={index}>
                  <strong>{record.code || "Note"}</strong>
                  {`${record.count != null ? ` (${num(record.count, 0)})` : ""}: ${record.message || String(note)}`}
                </li>
              );
            })}
          </ul>
        </details>
      )}
      {sources.length > 0 && (
        <details
          className="analysis-diagnostics metric-source-diagnostics"
          open
          data-embed-hidden={hidden || undefined}
        >
          <summary>Metric source notes</summary>
          {sources.some((source) => Object.keys(source.skipped ?? {}).length) && (
            <p>
              Omitted records fall outside the source’s selected storage or lack the endpoints or
              values required for evaluation. A zero does not account for omitted activity.
            </p>
          )}
          {sources.some((source) => Object.keys(source.uncertain ?? {}).length) && (
            <p>
              Some recorded values are retained with an unresolved normalization rule. Their metric
              results may differ from the native analysis.
            </p>
          )}
          <ul>
            {sources.map((source, index) => (
              <li key={index}>
                <strong>{source.source}</strong>
                {` · ${locName(source.location)} · ${source.kind}: ${REASONS.flatMap(
                  ([label, key]) => {
                    const entries = Object.entries(source[key] ?? {});
                    return entries.length
                      ? `${label}: ${entries.map(([reason, count]) => `${reason.replaceAll("-", " ")} (${num(count, 0)})`).join(", ")}`
                      : [];
                  },
                ).join("; ")}`}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
