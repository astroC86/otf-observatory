import { useUi } from "./state/useUi";

export default function Brush() {
  const { brush } = useUi(({ brush }) => ({ brush }));
  return brush ? (
    <div className="drag-selection" style={{ position: "fixed", zIndex: 25, ...brush }} />
  ) : null;
}
