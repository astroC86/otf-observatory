import type { ReactNode } from "react";
export function EmptyState({ title, detail = "" }: { title: ReactNode; detail?: ReactNode }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {detail}
    </div>
  );
}
