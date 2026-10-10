import {
  useCallback,
  useContext,
  useLayoutEffect,
  useRef,
  type CanvasHTMLAttributes,
  type DependencyList,
  type Ref,
} from "react";
import { disposeCanvas } from "../../charts/interactions";
import { registerRedraw } from "../../charts/redraw";
import type { CanvasDraw } from "../../charts/types";
import { drawChart } from "../../charts/draw";
import type { ChartSpec } from "../../charts/specs";
import { embedTarget } from "../../embed/target";
import { useEmbedPresence } from "../../embed/useEmbedPresence";
import { registerCanvas } from "./canvasRegistry";
import { ViewStateContext } from "../../views/ViewStateContext";
import { active, beginViewWork } from "../../state/viewActions";
export type ChartProps = Omit<CanvasHTMLAttributes<HTMLCanvasElement>, "className"> & {
  className?: string | null;
  deps?: DependencyList;
  canvasRef?: Ref<HTMLCanvasElement>;
} & ({ spec: ChartSpec; draw?: never } | { draw: CanvasDraw; spec?: never });
export function Chart({ spec, draw, deps, canvasRef, className = "chart", ...props }: ChartProps) {
  const snapshot = useContext(ViewStateContext);
  const ref = useRef<HTMLCanvasElement>(null);
  const setRef = useCallback(
    (element: HTMLCanvasElement | null) => {
      ref.current = element;
      if (typeof canvasRef === "function") return canvasRef(element);
      if (canvasRef) canvasRef.current = element;
    },
    [canvasRef],
  );
  useEmbedPresence(Boolean(embedTarget && props.id === embedTarget));
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const unregisterCanvas = registerCanvas(element, props.id !== "overview");
    let cleanup: void | (() => void);
    let finish = snapshot ? beginViewWork(snapshot.epoch) : undefined;
    const unregister = registerRedraw(() => {
      if (snapshot && !active(snapshot.epoch)) return;
      try {
        cleanup?.();
        const result = spec ? drawChart(element, spec) : draw(element);
        cleanup = typeof result === "function" ? result : undefined;
      } finally {
        finish?.();
        finish = undefined;
      }
    });
    return () => {
      unregister();
      unregisterCanvas();
      finish?.();
      cleanup?.();
      disposeCanvas(element);
    };
  }, [
    snapshot?.epoch,
    ...(deps ?? [
      props.id,
      draw,
      spec?.type,
      spec && "data" in spec && spec.data,
      spec && "options" in spec && spec.options,
      spec && "height" in spec && spec.height,
      spec && "key" in spec && spec.key,
      spec && "compact" in spec && spec.compact,
      spec && "visible" in spec && spec.visible,
      spec && "messages" in spec && spec.messages,
      spec && "detail" in spec && spec.detail,
      spec && "draw" in spec && spec.draw,
      spec && "intervals" in spec && spec.intervals,
      spec && "edges" in spec && spec.edges,
      spec && "nodes" in spec && spec.nodes,
      spec && "wait" in spec && spec.wait,
      spec && "page" in spec && spec.page,
      spec && "onEvidence" in spec && spec.onEvidence,
    ]),
  ]);
  return <canvas ref={setRef} className={className ?? undefined} {...props} />;
}
