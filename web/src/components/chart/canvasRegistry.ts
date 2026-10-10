const canvases = new Set<HTMLCanvasElement>();
export function registerCanvas(element: HTMLCanvasElement, exportable = true) {
  if (exportable) canvases.add(element);
  return () => {
    canvases.delete(element);
  };
}
export function firstChart() {
  let first: HTMLCanvasElement | null = null;
  for (const canvas of canvases) {
    if (!canvas.isConnected) continue;
    if (!first || canvas.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING)
      first = canvas;
  }
  return first;
}
