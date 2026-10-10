import { useMemo } from "react";
import { bytes } from "../../lib/format/bytes";
import { compact, num } from "../../lib/format/numbers";
import { inspectObject } from "../../state/inspection";
import { shortLoc } from "../../state/selectors";
import { Card } from "../../components/panel/Card";
import { Chart } from "../../components/chart/Chart";
import { ChartGroup } from "../../components/chart/ChartGroup";
import { ControlBar } from "../../components/controls/ControlBar";
import { DataTable } from "../../components/table/DataTable";
import { StatGrid } from "../../components/ui/StatGrid";
import { bytesCol, timeCol } from "../../components/table/columns";
import { TransferSummary } from "./transfers/TransferSummary";
import { TransferMatrix } from "./transfers/TransferMatrix";
import { TransferTimeline } from "./transfers/TransferTimeline";
import type { ColumnDef } from "../../components/table/types";
import { useExport } from "../../hooks/useExport";
import type { ViewState } from "../../state/types";
import type { MessageRow } from "../../api/types/data";
import { pageButton, updateQuery } from "../shared/dataControls";
import { MessageFilters } from "./MessageFilters";
import type { CommunicationData } from "./types";
import { selectControl } from "../../components/controls/factories";

const messageColumns: ColumnDef<MessageRow>[] = [
  {
    key: "source",
    label: "Sender",
    render: (_, row) => `${shortLoc(row.source) ?? ""}`,
  },
  {
    key: "target",
    label: "Receiver",
    render: (_, row) => `${shortLoc(row.target) ?? ""}`,
  },
  timeCol<MessageRow>("start", "Send"),
  timeCol<MessageRow>("end", "Receive"),
  bytesCol<MessageRow>("bytes", "Payload"),
  { key: "tag", label: "Tag" },
  { key: "comm", label: "Comm" },
  {
    key: "bandwidth",
    label: "Apparent rate",
    number: true,
    render: (_, row) => (row.bandwidth == null ? "—" : `${bytes(row.bandwidth)}/s`),
  },
  { key: "status", label: "Status" },
];

function transferProps<T>(result: PromiseSettledResult<T>) {
  if (result.status === "fulfilled") return { data: result.value, error: null };
  const error: unknown = result.reason;
  return {
    data: null,
    error: error instanceof Error ? error.message : String(error),
  };
}

export function CommunicationPanel({
  result,
  snapshot,
}: {
  result: CommunicationData;
  snapshot: ViewState;
}) {
  const data = result.messages;
  useExport(data.rows, "mpi-messages");
  const { totalBytes, matched, histogram, summary, matrix, timeline } = useMemo(
    () => ({
      totalBytes: data.matrix.reduce((sum, row) => sum + row.bytes, 0),
      matched: data.matrix.reduce((sum, row) => sum + row.matched, 0),
      histogram: data.histogram.map((row) => ({
        ...row,
        name: snapshot.messageBy === "size" ? bytes(Number(row.label)) : String(row.label),
        id: String(row.label),
      })),
      summary: transferProps(result.summary),
      matrix: transferProps(result.matrix),
      timeline: transferProps(result.timeline),
    }),
    [data, result, snapshot.messageBy],
  );
  return (
    <>
      <StatGrid
        details={false}
        items={[
          { label: "Messages", value: compact(data.total) },
          { label: "Payload", value: bytes(totalBytes) },
          {
            label: "Matched",
            value: `${num(data.total ? (matched / data.total) * 100 : 0, 2)}%`,
          },
          { label: "Communicating pairs", value: num(data.matrix.length, 0) },
        ]}
      />
      <MessageFilters filter={snapshot.messageFilter} />
      <ChartGroup className="dashboard-grid">
        <Card
          title="Communication matrix"
          controls={[
            selectControl(
              "matrix-metric",
              undefined,
              snapshot.matrixMetric,
              [
                ["bytes", "Bytes"],
                ["count", "Message count"],
                ["duration", "Mean transfer time"],
              ],
              (value) => updateQuery({ matrixMetric: value }),
              {
                ariaLabel: "Communication matrix metric",
              },
            ),
          ]}
        >
          <Chart
            id="matrix-chart"
            aria-label="Communication matrix"
            spec={{ type: "matrix", data: data.matrix }}
          />
        </Card>
        <Card
          title="Message distribution"
          controls={[
            selectControl(
              "message-group",
              undefined,
              snapshot.messageBy,
              [
                ["size", "Message size"],
                ["tag", "Tag"],
                ["communicator", "Communicator"],
                ["status", "Status"],
              ],
              (value) => updateQuery({ messageBy: value }),
              {
                ariaLabel: "Group message histogram",
              },
            ),
          ]}
        >
          <Chart
            id="message-histogram"
            aria-label="Message distribution"
            spec={{ type: "bars", data: histogram, key: "count", height: 440 }}
          />
        </Card>
      </ChartGroup>
      <Card
        title="Message records"
        tools={
          <ControlBar
            className="pager"
            controls={[
              pageButton("messages-prev", "messageOffset", -500, snapshot.messageOffset === 0),
              {
                kind: "content",
                children: (
                  <span>{`${num(snapshot.messageOffset + 1, 0)}–${num(Math.min(data.total, snapshot.messageOffset + 500), 0)} / ${num(data.total, 0)}`}</span>
                ),
              },
              pageButton(
                "messages-next",
                "messageOffset",
                500,
                snapshot.messageOffset + 500 >= data.total,
              ),
            ]}
          />
        }
        caption={
          <span>{`Transfer time is the trace send-to-receive interval. Apparent rate includes waiting. Matrices above 48 locations aggregate contiguous location blocks.`}</span>
        }
      >
        <DataTable
          id="message-table"
          rows={data.rows}
          columns={messageColumns}
          onRow={(row) => inspectObject("MPI message", row)}
        />
      </Card>
      <TransferTimeline {...timeline} />
      <TransferMatrix {...matrix} />
      <TransferSummary {...summary} />
    </>
  );
}
