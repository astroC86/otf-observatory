import { useState } from "react";
import { ControlBar } from "../../components/controls/ControlBar";
import type { MessageFilter } from "../../api/types/common";
import { updateQuery } from "../shared/dataControls";
import { useEmbedHidden } from "../../embed/useEmbedHidden";
import { numberControl, selectControl, buttonControl } from "../../components/controls/factories";

export function MessageFilters({ filter }: { filter: Readonly<MessageFilter> }) {
  const hidden = useEmbedHidden();
  const [draft, setDraft] = useState(() => ({
    tag: filter.tag || "",
    comm: filter.comm || "",
    minBytes: filter.minBytes || "",
    status: filter.status || "",
  }));
  const text = (key: keyof typeof draft) => (value: string) =>
    setDraft((previous) => ({ ...previous, [key]: value }));
  return (
    <div className="card" data-embed-hidden={hidden || undefined}>
      <ControlBar
        controls={[
          {
            kind: "text",
            id: "message-tag",
            label: "Tag",
            value: draft.tag,
            placeholder: "Any",
            size: 5,
            onChange: text("tag"),
          },
          {
            kind: "text",
            id: "message-comm",
            label: "Communicator",
            value: draft.comm,
            placeholder: "Any",
            size: 6,
            onChange: text("comm"),
          },
          numberControl("message-min", "Min bytes", draft.minBytes, text("minBytes"), {
            min: 0,
            placeholder: "0",
            size: 6,
          }),
          selectControl(
            "message-status",
            "Status",
            draft.status,
            [["", "All"], "matched", "unmatched send", "unmatched receive", "clock inversion"],
            text("status"),
          ),
          buttonControl("apply-message-filter", "Apply filters", () =>
            updateQuery({ messageFilter: { ...draft }, messageOffset: 0 }),
          ),
          buttonControl("clear-message-filter", "Clear", () =>
            updateQuery({ messageFilter: {}, messageOffset: 0 }),
          ),
        ]}
      />
    </div>
  );
}
