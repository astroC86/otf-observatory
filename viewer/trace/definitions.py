"""Definition storage, clock conversion and finalized trace metadata."""

import collections
import functools
import itertools
import json
import pathlib
import time

from ..mpi.communicators import Communicators
from ..mpi.rma_matching import RMA_INDEX_VERSION
from ..tasks.identity import TASK_INDEX_VERSION
from .encoding import dumps
from .schema import MESSAGE_INDEX_VERSION, VERSION

ROOT = pathlib.Path(__file__).resolve().parents[2]


ENUMS = (
    json.loads((ROOT / "native/build/enums.json").read_text())
    if (ROOT / "native/build/enums.json").exists()
    else {}
)


@functools.cache
def _enum_names(prefix):
    """First matching OTF2 constant name for each value, in ENUMS order."""
    names = {}
    for k, v in ENUMS.items():
        if k.startswith(prefix) and not (
            prefix == "OTF2_PARADIGM_" and ("_CLASS_" in k or "_PROPERTY_" in k)
        ):
            names.setdefault(v, k[len(prefix) :])
    return names


def enum(prefix, value):
    try:
        return _enum_names(prefix).get(value, str(value))
    except TypeError:  # unhashable values never equal a numeric constant
        return str(value)


class DefinitionIndex:
    """Shared definition and buffered database state for derived indexes."""

    def __init__(self, db, progress=lambda **kw: None):
        self.db = db
        self.progress = progress
        self.defs = collections.defaultdict(dict)
        self.communicators = Communicators(self.defs)
        self.record_counts = collections.Counter()
        self.next_event = 0
        self.offset = 0
        self.resolution = 1
        self.length = 0
        self.max_time = 0
        self.warnings = collections.Counter()
        self.event_counts = collections.Counter()
        self.batches = collections.defaultdict(list)
        self.location_counts = collections.Counter()

    def add(self, table, row):
        b = self.batches[table]
        b.append(row)
        if len(b) >= 8000:
            self.flush(table)

    def flush(self, table=None):
        for t in ([table] if table else list(self.batches)):
            b = self.batches[t]
            if b:
                # Bind several rows per SQLite step without growing the buffer.
                # Stay within even SQLite's older 999-variable default limit.
                values = "(" + ",".join("?" for _ in b[0]) + ")"
                rows = 999 // len(b[0])
                full = len(b) // rows * rows
                prefix = f"INSERT INTO {t} VALUES "
                if full:
                    self.db.executemany(
                        prefix + ",".join([values] * rows),
                        (
                            tuple(
                                itertools.chain.from_iterable(b[start : start + rows])
                            )
                            for start in range(0, full, rows)
                        ),
                    )
                if full < len(b):
                    self.db.execute(
                        prefix + ",".join([values] * (len(b) - full)),
                        tuple(itertools.chain.from_iterable(b[full:])),
                    )
                b.clear()

    def definition(self, kind, d):
        ref = str(d.get("self", self.record_counts[kind]))
        self.defs[kind][ref] = d
        self.communicators.invalidate()
        self.record_counts[kind] += 1
        self.add("definitions", (kind, ref, dumps(d)))
        if kind == "ClockProperties":
            self.offset = d["globalOffset"]
            self.resolution = d["timerResolution"]
            if self.resolution <= 0:
                raise ValueError("Invalid OTF timer resolution")
            self.length = d["traceLength"] / self.resolution

    def string(self, ref):
        return self.defs["String"].get(str(ref), {}).get("string", "")

    def seconds(self, tick):
        return (tick - self.offset) / self.resolution

    def marker(self, kind, d):
        if kind == "DefMarker":
            self.defs[kind][str(d["self"])] = d
            self.add("definitions", (kind, str(d["self"]), dumps(d)))
        elif kind == "Marker":
            md = self.defs["DefMarker"].get(str(d["marker"]), {})
            self.add(
                "markers",
                (
                    None,
                    self.seconds(d["timestamp"]),
                    d["duration"] / self.resolution,
                    str(d["scopeRef"]),
                    d["text"],
                    md.get("markerCategory", ""),
                    enum("OTF2_MARKER_SEVERITY_", md.get("severity", 0)),
                    dumps(d),
                ),
            )

    def metadata(self, path):
        regions = [
            dict(
                id=k,
                name=self.string(d["name"]),
                group=d.get("groupName")
                or enum("OTF2_PARADIGM_", d.get("paradigm", 0)),
                role=enum("OTF2_REGION_ROLE_", d.get("regionRole", 0)),
                file=self.string(d.get("sourceFile")),
                line=d.get("beginLineNumber", 0),
            )
            for k, d in self.defs["Region"].items()
        ]
        groups = [
            dict(
                id=k,
                name=self.string(d["name"]),
                parent=str(d.get("systemTreeParent", "")),
                type=enum("OTF2_LOCATION_GROUP_TYPE_", d.get("locationGroupType", 0)),
            )
            for k, d in self.defs["LocationGroup"].items()
        ]
        locations = [
            dict(
                id=k,
                name=self.string(d["name"]) or f"Location {k}",
                group=str(d["locationGroup"]),
                type=enum("OTF2_LOCATION_TYPE_", d["locationType"]),
                events=self.location_counts[k],
            )
            for k, d in self.defs["Location"].items()
        ]
        metrics = [
            dict(
                id=k,
                name=self.string(d["name"]),
                unit=self.string(d["unit"]),
                mode=enum("OTF2_METRIC_", d["metricMode"]),
                modeValue=d["metricMode"],
                description=self.string(d.get("description")),
                valueType=enum("OTF2_TYPE_", d.get("valueType", 0)),
                base=d.get("base", 1),
                exponent=d.get("exponent", 0),
            )
            for k, d in self.defs["MetricMember"].items()
        ]
        nodes = [
            dict(
                id=k,
                name=self.string(d["name"]),
                className=self.string(d["className"]),
                parent=str(d["parent"]),
            )
            for k, d in self.defs["SystemTreeNode"].items()
        ]
        files = {
            k: self.string(d["name"]) for k, d in self.defs["IoRegularFile"].items()
        }
        counts = {
            t: self.db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in [
                "events",
                "spans",
                "messages",
                "metrics",
                "collectives",
                "io",
                "rma",
                "samples",
                "markers",
            ]
        }
        meta = dict(
            name=path.parent.name + "/" + path.name,
            path=str(path),
            format="OTF2" if path.suffix == ".otf2" else "OTF",
            duration=max(self.length, self.max_time),
            clock=dict(resolution=str(self.resolution), offset=str(self.offset)),
            counts=counts,
            regions=regions,
            locations=locations,
            groups=groups,
            metrics=metrics,
            nodes=nodes,
            files=files,
            eventTypes=dict(self.event_counts),
            warnings={k: v for k, v in self.warnings.items() if v},
            version=VERSION,
            taskIndexVersion=TASK_INDEX_VERSION,
            importSeconds=round(time.monotonic() - self.started, 2),
        )
        self.db.execute("INSERT INTO metadata VALUES (?,?)", ("trace", dumps(meta)))
        self.db.execute(
            "INSERT INTO metadata VALUES (?,?)",
            ("message_index_version", str(MESSAGE_INDEX_VERSION)),
        )
        self.db.execute(
            "INSERT INTO metadata VALUES (?,?)",
            ("rma_index_version", str(RMA_INDEX_VERSION)),
        )
        self.db.commit()
        return meta
