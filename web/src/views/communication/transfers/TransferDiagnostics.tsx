import type { TransferSummaryResponse } from "../../../api/types/transfers";
import { num } from "../../../lib/format/numbers";

export function TransferDiagnostics({
  notes,
}: {
  readonly notes: TransferSummaryResponse["diagnostics"] | undefined;
}) {
  if (!notes?.length) return null;
  return (
    <details className="analysis-diagnostics" open>
      <summary>Omitted transfer records</summary>
      <ul>
        {notes.map((note, index) => (
          <li key={index}>{`${note.code.replaceAll("-", " ")}: ${num(note.count, 0)}`}</li>
        ))}
      </ul>
    </details>
  );
}
