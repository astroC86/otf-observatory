"""Load recorded I/O, MPI and RMA operations as signal sources."""

import collections
import json

from . import limits
from .operation_signals import operation_signal
from .patterns import io_paradigm_ids
from .rma_sources import rma_transfer_rows
from .series import Data, Series
from .values import MISSING_ATTRIBUTE, source_number


class OperationSources:
    """Own cached RMA transfers for a bounded metric query."""

    def __init__(self, context):
        self.context = context
        self.rma_sources = {}

    def load(self, kind, spec):
        ctx = self.context
        q, locs = ctx.scoped(spec)
        operations = collections.defaultdict(list)
        uncertain = collections.defaultdict(collections.Counter)
        omitted = collections.defaultdict(collections.Counter)
        q = dict(q, start=0.0, end=float(ctx.trace.meta["duration"]))
        is_io = kind.startswith("io_")
        transfer_types = None
        if not is_io and spec.get("transferTypes") not in (None, ""):
            raw_types = spec["transferTypes"]
            if isinstance(raw_types, str):
                raw_types = raw_types.split(",")
            if not isinstance(raw_types, list) or len(raw_types) > 260:
                raise ValueError(
                    "Transfer types must be a comma-separated list of native type IDs"
                )
            try:
                transfer_types = {int(value) for value in raw_types}
            except (ValueError, TypeError, OverflowError) as error:
                raise ValueError("Invalid native transfer type ID") from error
            if any(value < -4 or value > 255 for value in transfer_types):
                raise ValueError("Native transfer type ID is out of range")
        if is_io:
            start, end, where, args = ctx.trace.scope(q, regions=False)
            where = "1" + where
            if spec.get("operation"):
                where += " AND instr(lower(operation),?)>0"
                args.append(str(spec["operation"]).casefold())
            if spec.get("handle") not in (None, ""):
                where += " AND handle=?"
                args.append(str(spec["handle"]))
            if spec.get("paradigm") not in (None, ""):
                paradigms = io_paradigm_ids(ctx.trace, spec["paradigm"])
                handles = [
                    str(ref)
                    for ref, definition in ctx.trace.defs.get("IoHandle", {}).items()
                    if str(definition.get("ioParadigm")) in paradigms
                ]
                where += (
                    " AND handle IN (" + ",".join("?" for _ in handles) + ")"
                    if handles
                    else " AND 0"
                )
                args += handles
            if spec.get("file"):
                candidate = str(spec["file"])
                files = [
                    str(k)
                    for k, v in ctx.trace.meta.get("files", {}).items()
                    if candidate == str(k) or candidate.casefold() in str(v).casefold()
                ]
                where += (
                    " AND file IN (" + ",".join("?" for _ in files) + ")"
                    if files
                    else " AND 0"
                )
                args += files
        else:
            marks = ",".join("?" for _ in locs) or "''"
            where = "(source IN (" + marks + ") OR target IN (" + marks + "))"
            args = locs + locs
            for option in ("tag", "comm", "status"):
                if q.get(option):
                    where += " AND " + option + "=?"
                    args.append(q[option])
            for option, op in [("minBytes", ">="), ("maxBytes", "<=")]:
                if q.get(option):
                    where += " AND bytes" + op + "?"
                    args.append(int(q[option]))
        direction = spec.get("direction", "send")
        if direction not in ("send", "receive", "both"):
            raise ValueError("Message direction must be send, receive or both")
        select = (
            "SELECT * FROM io"
            if is_io
            else (
                "SELECT m.*, e.native_start, e.native_end, e.emitter AS native_emitter, e.emission_event "
                "FROM messages m LEFT JOIN message_evidence e ON e.send_event=m.send_event AND e.recv_event=m.recv_event"
            )
        )
        ordering = "coalesce(start,end),id" if is_io else "coalesce(m.start,m.end),m.id"
        for row in ctx.fetch(
            select + " WHERE " + where + " ORDER BY " + ordering, args
        ):
            if not is_io and transfer_types is not None and -2 not in transfer_types:
                continue
            targets = (
                [row["location"]]
                if is_io
                else (
                    [row.get("source")]
                    if direction == "send"
                    else (
                        [row.get("target")]
                        if direction == "receive"
                        else list(dict.fromkeys([row.get("source"), row.get("target")]))
                    )
                )
            )
            if not is_io and row.get("native_emitter") == "incomplete-unverified":
                # Native OTF2 EOF/destruction drops pending operations without
                # emitting MsgCom records (1064070 -> ff5240 -> 10ebf10).
                # The archive index retains its synthesized release for raw
                # inspection, but it is not a native metric observation.
                for loc in targets:
                    if loc in locs:
                        omitted[loc]["non-native-end-of-trace-release"] += 1
                continue
            a = row.get("start")
            b = row.get("end")
            native_bounds = (
                not is_io
                and row.get("native_emitter") in ("send", "receive")
                and row.get("native_start") is not None
                and row.get("native_end") is not None
            )
            if native_bounds:
                a = row["native_start"]
                b = row["native_end"]
            length = (b - a) if a is not None and b is not None else None
            for loc in targets:
                if loc not in locs:
                    continue
                if not is_io and a is not None and b is not None and b < a:
                    uncertain[loc]["clock-inversion-native-normalization"] += 1
                value = None
                if kind == "io_attribute":
                    wanted = spec.get("attribute", "bytes")
                    value = length if wanted == "duration" else row.get(wanted)
                    if wanted not in row and wanted != "duration":
                        raw = list(
                            ctx.fetch(
                                "SELECT data FROM events WHERE id=?", (row["event"],)
                            )
                        )
                        completion = json.loads(raw[0]["data"]) if raw else {}
                        value = ctx.attribute(
                            completion, wanted, MISSING_ATTRIBUTE, decode_strings=False
                        )
                        if value is MISSING_ATTRIBUTE:
                            begins = ctx.fetch(
                                "SELECT data FROM events WHERE location=? AND time=? AND kind='IoOperationBegin' ORDER BY id",
                                (row["location"], a),
                            )
                            for begin in begins:
                                attributes = json.loads(begin["data"])
                                same_match = "matchingId" not in completion or str(
                                    attributes.get("matchingId")
                                ) == str(completion["matchingId"])
                                if same_match and str(attributes.get("handle")) == str(
                                    row["handle"]
                                ):
                                    value = ctx.attribute(
                                        attributes,
                                        wanted,
                                        MISSING_ATTRIBUTE,
                                        decode_strings=False,
                                    )
                                    if value is not MISSING_ATTRIBUTE:
                                        break
                    value = source_number(value)
                sequence = (
                    row["id"]
                    if is_io
                    else (row.get("emission_event") or row["id"], row["id"])
                )
                operations[loc].append(
                    dict(
                        start=a,
                        end=b,
                        bytes=row.get("bytes"),
                        attribute=value,
                        sequence=sequence,
                        family="io" if is_io else "mpi",
                        order_proven=is_io or row.get("emission_event") is not None,
                    )
                )
        if (
            not is_io
            and (not q.get("tag") or str(q["tag"]) == "-1")
            and (transfer_types is None or transfer_types - {-2})
        ):
            cache_key = tuple(locs)
            if cache_key not in self.rma_sources:
                self.rma_sources[cache_key] = rma_transfer_rows(
                    ctx.trace,
                    locations=locs,
                    limit=limits.MAX_INPUT_POINTS,
                    charge=lambda count: ctx.charge(count, True),
                )
            rma = self.rma_sources[cache_key]
            if rma["skipped"]:
                ctx.source_diagnostics.append(
                    dict(
                        source=ctx.source_names[-1] if ctx.source_names else "",
                        location="all",
                        kind=kind,
                        skipped={
                            "rma-" + reason: count
                            for reason, count in rma["skipped"].items()
                        },
                    )
                )
            for row in rma["rows"]:
                if (
                    transfer_types is not None
                    and row["nativeType"] not in transfer_types
                ):
                    continue
                if any(
                    q.get(option) and str(q[option]) != str(row.get(option))
                    for option in ("comm", "status")
                ):
                    continue
                if q.get("minBytes") and row["bytes"] < int(q["minBytes"]):
                    continue
                if q.get("maxBytes") and row["bytes"] > int(q["maxBytes"]):
                    continue
                targets = (
                    [row["sender"]]
                    if direction == "send"
                    else (
                        [row["receiver"]]
                        if direction == "receive"
                        else list(dict.fromkeys([row["sender"], row["receiver"]]))
                    )
                )
                for loc in targets:
                    if loc in locs:
                        operations[loc].append(
                            dict(
                                start=row["start"],
                                end=row["end"],
                                bytes=row["bytes"],
                                sequence=row["sequence"],
                                family="rma",
                                order_proven=True,
                            )
                        )
            # A fabricated/older index can lack the resolving MPI event. It
            # cannot prove ordering against a same-time RMA operation, which
            # matters to the overwritten transfer-time pulse.
            for loc, rows in operations.items():
                by_start = collections.defaultdict(list)
                for row in rows:
                    by_start[row["start"]].append(row)
                for same_time in by_start.values():
                    if len({row["family"] for row in same_time}) > 1 and any(
                        not row["order_proven"] for row in same_time
                    ):
                        uncertain[loc]["mixed-transfer-emission-order"] += 1
        try:
            resolution = int(ctx.trace.meta.get("clock", {}).get("resolution", 0))
        except (TypeError, ValueError, OverflowError):
            resolution = 0
        if resolution <= 0:
            raise ValueError(
                "Operation metrics require the recorded trace clock resolution"
            )
        signals = {}
        for loc in locs:
            result = operation_signal(
                operations[loc],
                family="io" if is_io else "message",
                mode=kind,
                tick_seconds=1 / resolution,
                reducer=spec.get("operationReduction", "sum"),
                charge=ctx.charge,
            )
            signals[loc] = Series(result.points, flags=result.flags)
            skipped = dict(collections.Counter(result.skipped) + omitted[loc])
            if skipped or uncertain[loc]:
                diagnosis = dict(
                    source=ctx.source_names[-1] if ctx.source_names else "",
                    location=loc,
                    kind=kind,
                    skipped=skipped,
                )
                if uncertain[loc]:
                    diagnosis["uncertain"] = dict(uncertain[loc])
                ctx.source_diagnostics.append(diagnosis)
        unit = (
            "B/s"
            if kind in ("io_bandwidth", "message_rate")
            else (
                "B"
                if kind in ("io_size", "message_volume")
                else (
                    "s"
                    if kind == "message_duration"
                    or (kind == "io_attribute" and spec.get("attribute") == "duration")
                    else ""
                )
            )
        )
        if kind in ("io_count", "message_count"):
            unit = "count"
        return Data(signals, unit)
