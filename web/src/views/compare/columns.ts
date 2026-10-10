import { col, countCol, timeCol } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import { num } from "../../lib/format/numbers";
import type { AnchorMatch, AnchorPair, ComparisonRow, EnsembleRun } from "./types";

export const comparisonColumns: ColumnDef<ComparisonRow>[] = [
  col("name", "Function"),
  timeCol("a", "Baseline exclusive"),
  timeCol("b", "Comparison exclusive"),
  timeCol("delta", "Delta"),
  { ...countCol("ratio", "Ratio"), format: (value) => (value == null ? "—" : `${num(value, 3)}×`) },
  countCol("callsA", "Baseline calls"),
  countCol("callsB", "Comparison calls"),
];
export const anchorColumns: ColumnDef<AnchorMatch>[] = [
  col("label", "Anchor"),
  col("kind", "Kind"),
  timeCol("timeA", "Baseline"),
  timeCol("timeB", "Comparison"),
  timeCol("residual", "Fit residual"),
];
export const ambiguityColumns: ColumnDef<AnchorPair & { rank: number }>[] = [
  col("rank", "Sequence position"),
  col("label", "Anchor"),
  timeCol("timeA", "Baseline"),
  timeCol("timeB", "Comparison"),
];
type EnsembleRow = EnsembleRun &
  Record<"runNumber" | "matched" | "shift" | "scale" | "residual", number> & { status: string };
export const ensembleColumns: ColumnDef<EnsembleRow>[] = [
  countCol("runNumber", "Run"),
  col("name", "Run"),
  col("status", "Correspondence"),
  countCol("matched", "Matched anchors"),
  timeCol("shift", "Offset"),
  { ...countCol("scale", "Scale"), format: (value) => num(value, 8) },
  timeCol("residual", "95% residual"),
];
export const mappingOptions = [
  ["affine", "Global offset + scale"],
  ["piecewise", "Piecewise anchor mapping"],
] as const;
export const ensembleOptions = mappingOptions.toReversed();
