const redraws = new Set<() => void>();
const frames = new Map<() => void, number>();

export function registerRedraw(draw: () => void): () => void {
  redraws.add(draw);
  frames.set(
    draw,
    requestAnimationFrame(() => {
      frames.delete(draw);
      if (redraws.has(draw)) draw();
    }),
  );
  return () => unregister(draw);
}

function unregister(draw: () => void): void {
  redraws.delete(draw);
  const frame = frames.get(draw);
  if (frame !== undefined) cancelAnimationFrame(frame);
  frames.delete(draw);
}

export function redrawCharts(): void {
  for (const draw of redraws.keys()) draw();
}
