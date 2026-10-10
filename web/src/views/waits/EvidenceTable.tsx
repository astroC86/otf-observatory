import type { ReactNode } from "react";
import { Card } from "../../components/panel/Card";
import { ControlBar } from "../../components/controls/ControlBar";
import { DataTable, type DataTableProps } from "../../components/table/DataTable";
import { num } from "../../lib/format/numbers";
import { updateState } from "../../state/store";
import { scheduleRender } from "../../state/viewActions";

const PREFIXES = {
  waitOffset: "wait",
  waitCauseOffset: "wait-cause",
  waitRequestOffset: "wait-request",
  waitCollectiveOffset: "wait-collective",
  waitProbeOffset: "wait-probe",
  waitRmaLockOffset: "wait-rma-lock",
};
type Page = {
  field: keyof typeof PREFIXES;
  total: number;
  more?: boolean;
  offset: number;
  count?: number;
  limit?: number;
};
type Props<Row extends object> = DataTableProps<Row> & {
  title: string;
  caption?: string;
  before?: ReactNode;
  children?: ReactNode;
  page?: Page;
};

export function EvidenceTable<Row extends object>({
  title,
  caption,
  before,
  children,
  page,
  ...table
}: Props<Row>) {
  const offset = page?.offset ?? 0;
  const count = page?.count ?? table.rows.length;
  const causes = page?.field === "waitCauseOffset";
  function move(direction: number) {
    if (!page) return;
    updateState((previous) => ({
      [page.field]: Math.max(0, previous[page.field] + direction * (page.limit || 500)),
      ...(page.field === "waitOffset" ? { waitCauseOffset: 0 } : {}),
    }));
    scheduleRender();
  }
  const tools = page && (
    <ControlBar
      className={null}
      controls={[-1, 0, 1].map((direction) =>
        direction
          ? {
              kind: "button",
              id: `${PREFIXES[page.field]}-${direction < 0 ? "prev" : "next"}`,
              disabled: direction < 0 ? !offset : !page.more,
              ariaLabel: causes
                ? `${direction < 0 ? "Previous" : "Next"} dependency links`
                : undefined,
              children: direction < 0 ? "←" : "→",
              onClick: () => move(direction),
            }
          : {
              kind: "content",
              children: (
                <span>
                  {causes
                    ? `${offset}–${offset + count} / ${page.total} links for these calls`
                    : `${num(offset, 0)}–${num(offset + count, 0)} / ${num(page.total, 0)}`}
                </span>
              ),
            },
      )}
    />
  );
  return (
    <Card title={title} tools={tools} caption={caption && <span>{caption}</span>}>
      {before}
      <DataTable {...table} />
      {children}
    </Card>
  );
}
