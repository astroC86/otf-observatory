import { useUi } from "../state/useUi";

export default function Footer() {
  const { status, statusIcon, queryTime } = useUi(({ status, statusIcon, queryTime }) => ({
    status,
    statusIcon,
    queryTime,
  }));
  return (
    <footer>
      <span id="status">
        {statusIcon ? (
          <>
            <i />
            {` ${status}`}
          </>
        ) : (
          status
        )}
      </span>
      <span id="footer-hint">Drag to zoom · Shift-drag to pan · Double-click a call to focus</span>
      <span id="query-time">{queryTime}</span>
    </footer>
  );
}
