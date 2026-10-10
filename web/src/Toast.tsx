import { useUi } from "./state/useUi";

export default function Toast() {
  const { toast } = useUi(({ toast }) => ({ toast }));
  return (
    <div id="toast" role="status" hidden={!toast}>
      {toast}
    </div>
  );
}
