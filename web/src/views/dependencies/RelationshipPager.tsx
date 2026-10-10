import type { ReactNode } from "react";
import { updateQuery } from "../shared/dataControls";

const PAGES = {
  analysisPage: ["analysis", 1],
  relationshipOffset: ["relationship", 5000],
  gpuExternalOffset: ["gpu-external", 500],
} as const;

interface Props {
  field: keyof typeof PAGES;
  offset: number;
  more: boolean;
  children: ReactNode;
}

export function RelationshipPager({ field, offset, more, children }: Props) {
  const [prefix, step] = PAGES[field];
  const change = (direction: number) =>
    updateQuery((previous) => ({
      [field]: Math.max(
        0,
        (field === "analysisPage" ? offset : previous[field]) + direction * step,
      ),
    }));
  return (
    <>
      <button id={`${prefix}-prev`} disabled={!offset} onClick={() => change(-1)}>
        ←
      </button>
      <span>{children}</span>
      <button id={`${prefix}-next`} disabled={!more} onClick={() => change(1)}>
        →
      </button>
    </>
  );
}
