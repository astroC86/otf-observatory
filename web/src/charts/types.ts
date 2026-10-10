import type { ReactNode } from "react";
import type { OverviewData, Rows, TimeRange } from "../api/types/common";
import type {
  CallTreeRow,
  CounterResponse,
  CounterSeries,
  ProcessSummaryRow,
  TimelineRow,
} from "../api/types/execution";
import type {
  MessageHistogramRow,
  MessageMatrixRow,
  MessageRow,
  ResourceOperationRow,
} from "../api/types/data";

export interface ChartColors {
  readonly text: string;
  readonly muted: string;
  readonly grid: string;
  readonly panel: string;
  readonly accent: string;
}

export interface ChartCanvas {
  readonly el: HTMLCanvasElement;
  readonly ctx: CanvasRenderingContext2D;
  readonly w: number;
  readonly h: number;
  readonly c: ChartColors;
  readonly dark: boolean;
}

export interface ChartPoint {
  readonly x: number;
  readonly y: number;
}

export type ChartRange = Readonly<TimeRange>;

export interface ChartBrush {
  readonly left: number;
  readonly top: number;
  readonly width: number;
  readonly height: number;
}

export interface ChartHit<T extends object = object> extends ChartPoint {
  readonly w: number;
  readonly h: number;
  readonly data: T;
  // Defer expensive tooltip formatting until a hit is actually hovered.
  readonly tip?: ReactNode | (() => ReactNode);
}

export interface ChartOptions<T extends object = object> {
  readonly range?: boolean;
  readonly menu?: boolean;
  readonly onClick?: (hit: ChartHit<T>) => void;
  readonly onDoubleClick?: (hit: ChartHit<T>) => void;
  readonly onHover?: (hit: ChartHit<T> | null, event: PointerEvent) => void;
  readonly onBrush?: (rect: ChartBrush | null) => void;
  readonly onRange?: (start: number, end: number) => void;
  readonly rangeState?: () => ChartRange;
}

export interface TimelineChartRow extends Readonly<Omit<TimelineRow, "incomplete">> {
  readonly incomplete?: number | boolean;
}
export type TimelineChartData = Rows<TimelineChartRow>;
export type TimelineChartMessage = Pick<MessageRow, "source" | "target" | "start" | "end">;

export type BarChartMetric = "exclusive" | "inclusive" | "duration" | "count" | "bytes";

export interface BarChartRow extends Readonly<
  Partial<Pick<CallTreeRow, "region" | "name" | "exclusive" | "inclusive"> & MessageHistogramRow>
> {
  readonly id?: string | number;
}

export type MatrixChartMetric = "bytes" | "count" | "duration";

export type MatrixChartRow = MessageMatrixRow;
export type FlameChartRow = Readonly<Omit<CallTreeRow, "overlapping">>;
export type ProcessChartRow = Readonly<Pick<ProcessSummaryRow, "id" | "exclusive" | "groups">>;
export type LineChartPoint = CounterSeries["points"][number];
export type LineChartSeries = Readonly<Omit<CounterSeries, "min" | "max" | "samples">>;
export interface LineChartData extends Readonly<Pick<CounterResponse, "unit">> {
  readonly series: readonly LineChartSeries[];
  readonly metric?: CounterResponse["metric"];
}

export interface LineChartSample extends ChartRange {
  readonly location: string;
}

export type ResourceChartRow = Omit<ResourceOperationRow, "status">;
export type ResourceChartData = Rows<ResourceChartRow>;
export type OverviewChartData = OverviewData;

export type CanvasDraw = (element: HTMLCanvasElement) => void | ChartCanvas | (() => void);

export type { ChartSpec } from "./specs";
