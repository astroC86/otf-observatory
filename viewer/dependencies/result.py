"""Dependency graph accumulation, window selection, and response paging."""

import collections
import json


def _scope(trace, q):
    start, end, _, _ = trace.scope(q, regions=False)
    limit = max(20, min(5000, int(q.get("limit", 2000))))
    cap = max(1000, min(250000, int(q.get("scanLimit", 150000))))
    selected = set(str(q.get("locations", "")).split(",")) - {""}
    return start, end, selected, limit, cap


class _Result:
    def __init__(self, trace, q):
        self.trace = trace
        self.start, self.end, self.selected, self.limit, self.cap = _scope(trace, q)
        self.nodes = {}
        self.edges = []
        self.intervals = []
        self.diagnostics = collections.Counter()
        self.messages = {}
        self.scanned = 0
        self.scan_truncated = False
        self.extra = {}
        self.offset = max(0, int(q.get("offset", 0)))
        self.kind = str(q.get("kind", ""))
        self.search = str(q.get("search", "")).casefold()

    def warn(self, code, message, count=1):
        self.diagnostics[code] += count
        self.messages[code] = message

    def node(self, event):
        ident = "event:" + str(event["id"])
        self.nodes.setdefault(
            ident,
            dict(
                id=ident,
                kind=event["kind"],
                label=event["kind"],
                location=str(event["location"]),
                time=event["time"],
                event=event["id"],
                data=event.get("data", {}),
            ),
        )
        return ident

    def edge(self, first, second, kind, label, confidence="recorded", data=None):
        source = self.node(first)
        target = self.node(second)
        self.edges.append(
            dict(
                id=f'{kind}:{first["id"]}:{second["id"]}',
                source=source,
                target=target,
                kind=kind,
                label=label,
                start=first["time"],
                end=second["time"],
                confidence=confidence,
                evidence=[first["id"], second["id"]],
                data=data or {},
            )
        )
        if second["time"] < first["time"]:
            self.warn(
                "clock-inversion",
                "Some recorded causal relationships run backwards in timestamp order; no negative elapsed time is reported.",
            )

    def interval(
        self,
        first,
        second,
        kind,
        label,
        data=None,
        confidence="recorded",
        status=None,
        end=None,
    ):
        b = second["time"] if second else (self.end if end is None else end)
        a = first["time"]
        if b < a:
            status = "clock inversion"
            b = a
        item = dict(
            id=f'{kind}:{first["id"]}',
            kind=kind,
            label=label,
            location=str(first["location"]),
            start=a,
            end=b,
            status=status or ("complete" if second else "open"),
            confidence=confidence,
            evidence=[first["id"]] + ([second["id"]] if second else []),
            data=data or {},
        )
        self.intervals.append(item)
        self.node(first)
        if second:
            self.node(second)
        return item

    def visible(self, start, end, locations):
        if self.start == self.end:
            return False
        return (
            min(start, end) < self.end
            and max(start, end) >= self.start
            and (not self.selected or any(str(x) in self.selected for x in locations))
        )

    def visible_interval(self, item):
        return self.visible(
            item["start"],
            item["end"],
            [item["location"], item["data"].get("source"), item["data"].get("target")],
        )

    def visible_edge(self, edge):
        return edge.get("context") or self.visible(
            edge["start"],
            edge["end"],
            [
                self.nodes[edge["source"]]["location"],
                self.nodes[edge["target"]]["location"],
            ],
        )

    def finish(self, summary=None):
        intervals = [i for i in self.intervals if self.visible_interval(i)]
        edges = [e for e in self.edges if self.visible_edge(e)]
        intervals.sort(key=lambda x: (x["start"], x["id"]))
        edges.sort(key=lambda x: (min(x["start"], x["end"]), x["id"]))
        counts = collections.Counter(i["kind"] for i in intervals)
        available_kinds = sorted(counts)
        durations = collections.Counter()
        for i in intervals:
            durations[i["kind"]] += max(
                0, min(i["end"], self.end) - max(i["start"], self.start)
            )
        total_intervals = len(intervals)
        total_edges = len(edges)
        if self.kind:
            intervals = [i for i in intervals if i["kind"] == self.kind]
        if self.search:
            intervals = [
                i for i in intervals if self.search in json.dumps(i).casefold()
            ]
            edges = [e for e in edges if self.search in json.dumps(e).casefold()]
        matched_intervals = len(intervals)
        matched_edges = len(edges)

        def representative(rows, limit):
            if len(rows) <= limit:
                return rows
            # Preserve each location/activity family and the beginning/end of
            # its entire selected range. These are real intervals, not invented
            # continuous bars spanning gaps between distinct operations.
            buckets = collections.defaultdict(list)
            for row in rows:
                buckets[(row.get("location", ""), row["kind"])].append(row)
            result = []
            left = limit
            for index, items in enumerate(buckets.values()):
                count = max(1, min(len(items), round(limit * len(items) / len(rows))))
                count = min(count, max(0, left - (len(buckets) - index - 1)))
                left -= count
                if count == 1:
                    result.append(items[len(items) // 2])
                elif count > 1:
                    result.extend(
                        items[round(i * (len(items) - 1) / (count - 1))]
                        for i in range(count)
                    )
            return sorted(result, key=lambda x: (x.get("start", 0), x["id"]))

        timeline_intervals = representative(intervals, self.limit)
        timeline_edges = representative(edges, min(3000, self.limit))
        intervals = intervals[self.offset : self.offset + self.limit]
        edges = edges[self.offset : self.offset + self.limit]
        ids = {e[k] for e in edges + timeline_edges for k in ("source", "target")}
        for interval in intervals + timeline_intervals:
            ids.update(
                "event:" + str(e)
                for e in interval["evidence"]
                if "event:" + str(e) in self.nodes
            )
        # Retain standalone events too, making missing matches inspectable.
        standalone = [
            n
            for n in self.nodes.values()
            if n["id"] not in ids
            and self.visible(n["time"], n["time"], [n["location"]])
        ]
        ids.update(n["id"] for n in standalone[: max(0, self.limit - len(ids))])
        summary = dict(
            summary or {},
            intervalCounts=dict(counts),
            durationSeconds=dict(durations),
            intervals=total_intervals,
            edges=total_edges,
            returnedIntervals=len(intervals),
            returnedEdges=len(edges),
            partial=self.scan_truncated,
        )
        return dict(
            window=dict(start=self.start, end=self.end),
            nodes=[self.nodes[i] for i in sorted(ids)],
            edges=edges,
            intervals=intervals,
            summary=summary,
            diagnostics=[
                dict(code=k, count=v, message=self.messages[k])
                for k, v in self.diagnostics.items()
            ],
            timelineIntervals=timeline_intervals,
            timelineEdges=timeline_edges,
            displayReduction=(
                "representative recorded intervals across the full time range"
                if matched_intervals > self.limit
                or matched_edges > min(3000, self.limit)
                else "none"
            ),
            offset=self.offset,
            intervalTotal=matched_intervals,
            edgeTotal=matched_edges,
            more=self.offset + self.limit < max(matched_intervals, matched_edges),
            truncated=self.scan_truncated,
            scannedEvents=self.scanned,
            availableKinds=available_kinds,
            **self.extra,
        )
