import { useCallback, useMemo, useRef, useState } from "react";
import { measureMetricGrid, metricGrid, type MetricChartMode, type MetricGrid } from "./metricGrid";

export function useMetricGrid(step: number, mode: MetricChartMode, onResize: () => void) {
  const [width, setWidth] = useState<number>();
  const grid = useMemo(
    () => (width === undefined ? undefined : metricGrid(width, step)),
    [width, step],
  );
  const initial = useRef<MetricGrid | undefined>(undefined);
  const changed = useRef(onResize);
  changed.current = onResize;
  const canvasRef = useCallback(
    (element: HTMLCanvasElement | null) => {
      if (!element) return;
      const measured = measureMetricGrid(element, step, mode);
      if (
        !initial.current ||
        initial.current.width !== measured.width ||
        initial.current.step !== measured.step
      ) {
        initial.current = measured;
        setWidth(measured.width);
      }
      let timer = 0;
      const observer = new ResizeObserver(() => {
        window.clearTimeout(timer);
        if (!element.isConnected) return;
        const next = measureMetricGrid(element, step, mode);
        const previous = initial.current;
        if (previous && next.width === previous.width && next.step === previous.step) return;
        timer = window.setTimeout(() => {
          if (!element.isConnected) return;
          initial.current = next;
          setWidth(next.width);
          changed.current();
        }, 120);
      });
      observer.observe(element);
      return () => {
        window.clearTimeout(timer);
        observer.disconnect();
      };
    },
    [step, mode],
  );
  return { grid, canvasRef };
}
