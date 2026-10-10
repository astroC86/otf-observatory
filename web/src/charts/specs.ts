import type {
  BarChartMetric,
  BarChartRow,
  CanvasDraw,
  ChartOptions,
  FlameChartRow,
  LineChartData,
  LineChartSample,
  MatrixChartRow,
  ProcessChartRow,
  ResourceChartData,
  ResourceChartRow,
  TimelineChartData,
  TimelineChartMessage,
  TimelineChartRow,
} from "./types";
import type { RelationshipChartData } from "./relationships";

interface DataSpec<Type, Data, Row extends object> {
  readonly type: Type;
  readonly data: Data;
  readonly options?: ChartOptions<Row>;
}
type RowSpec<Type, Row extends object> = DataSpec<Type, readonly Row[], Row>;

export type ChartSpec =
  | (DataSpec<"timeline", TimelineChartData, TimelineChartRow> & {
      readonly visible: readonly string[];
      readonly detail?: boolean;
      readonly messages?: readonly TimelineChartMessage[];
    })
  | (RowSpec<"bars", BarChartRow> & {
      readonly key?: BarChartMetric;
      readonly height?: number;
    })
  | (RowSpec<"matrix", MatrixChartRow> & { readonly compact?: boolean })
  | RowSpec<"flame", FlameChartRow>
  | RowSpec<"processes", ProcessChartRow>
  | (DataSpec<"lines", LineChartData, LineChartSample> & { readonly height?: number })
  | DataSpec<"resources", ResourceChartData, ResourceChartRow>
  | ({ readonly type: "relationships" } & RelationshipChartData)
  | { readonly type: "overview" }
  | { readonly type: "custom"; readonly draw: CanvasDraw };
