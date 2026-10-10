"""OTF 1.x ASCII records, retaining unknown records as original text."""

import heapq
import re

from ..otf1_aliases import parse_process_substitutes

HEX = r"[0-9a-f]+"
_TIME = re.compile(HEX).fullmatch
_ENTER = re.compile(r"E(" + HEX + r")").match
_LEAVE = re.compile(r"L(" + HEX + r")").match
_COUNTER = re.compile(r"CNT(" + HEX + r")V(" + HEX + r")").match
_MESSAGE = re.compile(
    r"([SR])(" + HEX + r")L(" + HEX + r")T(" + HEX + r")C(" + HEX + r")"
).match
_COLLECTIVE = re.compile(
    r"COP("
    + HEX
    + r")C("
    + HEX
    + r")RT("
    + HEX
    + r")S("
    + HEX
    + r")R("
    + HEX
    + r")D("
    + HEX
    + r")"
).match
_FILE = re.compile(
    r"F(" + HEX + r")H(" + HEX + r")OP(" + HEX + r")B(" + HEX + r")D(" + HEX + r")"
).match


def hx(s):
    return int(s, 16) if s else 0


def otf1_records(path):
    base = path.with_suffix("")
    strings = {}
    defs = []
    functions = {}
    func_groups = {}
    sources = {}
    files = {}
    counters = {}
    colls = {}
    resolution = 1

    def text(s):
        if s not in strings:
            ref = len(strings)
            strings[s] = ref
            defs.append(("String", dict(self=ref, string=s)))
        return strings[s]

    def quoted(s):
        m = re.search(r'NM"((?:\\.|[^"\\])*)"', s)
        return m[1].replace('\\"', '"').replace("\\\\", "\\") if m else ""

    all_defs = [base.parent / (base.name + ".0.def")] + [
        p
        for p in base.parent.glob(base.name + ".*.def*")
        if p.name != base.name + ".0.def"
    ]
    import gzip

    for dp in all_defs:
        if not dp.exists():
            continue
        with gzip.open(dp, "rt") if dp.suffix == ".z" else open(dp) as f:
            for line in f:
                s = line.strip()
                defs.append(("Otf1Definition", dict(raw=s)))
                if s.startswith(("DPS", "DEFPROCESSSUBSTITUTES")):
                    try:
                        substitution = parse_process_substitutes(s)
                    except ValueError:
                        substitution = None  # Raw record remains inspectable.
                    if substitution is not None:
                        defs.append(("Otf1ProcessSubstitutes", substitution))
                elif re.fullmatch(r"DTR(" + HEX + r")", s):
                    resolution = hx(s[3:])
                elif m := re.match(r"DP(" + HEX + r")NM", s):
                    n = hx(m[1])
                    defs.extend(
                        [
                            (
                                "LocationGroup",
                                dict(
                                    self=n,
                                    name=text(quoted(s)),
                                    locationGroupType=1,
                                    systemTreeParent=0,
                                ),
                            ),
                            (
                                "Location",
                                dict(
                                    self=n,
                                    name=text(quoted(s)),
                                    locationType=1,
                                    locationGroup=n,
                                    numberOfEvents=0,
                                ),
                            ),
                        ]
                    )
                elif m := re.match(r"DPG(" + HEX + r")M([^N]*)NM", s):
                    n = hx(m[1])
                    members = [hx(x) for x in m[2].split(",") if x]
                    defs.extend(
                        [
                            (
                                "Group",
                                dict(
                                    self=n,
                                    name=text(quoted(s)),
                                    groupType=1,
                                    paradigm=4,
                                    members=members,
                                ),
                            ),
                            (
                                "Comm",
                                dict(
                                    self=n,
                                    name=text(quoted(s)),
                                    group=n,
                                    parent=4294967295,
                                ),
                            ),
                        ]
                    )
                elif m := re.match(r"DFG(" + HEX + r")", s):
                    func_groups[hx(m[1])] = quoted(s)
                elif m := re.match(r"DSF(" + HEX + r")", s):
                    files[hx(m[1])] = quoted(s)
                elif m := re.match(
                    r"DS(" + HEX + r")F(" + HEX + r")LN(" + HEX + r")", s
                ):
                    sources[hx(m[1])] = (hx(m[2]), hx(m[3]))
                elif m := re.match(r"DF(" + HEX + r")G(" + HEX + r")", s):
                    src = re.search(r"X(" + HEX + r")$", s)
                    functions[hx(m[1])] = (
                        quoted(s),
                        hx(m[2]),
                        hx(src[1]) if src else 0,
                    )
                elif m := re.match(r"DFL(" + HEX + r")", s):
                    defs.append(
                        (
                            "IoRegularFile",
                            dict(self=hx(m[1]), name=text(quoted(s)), scope=0),
                        )
                    )
                elif m := re.match(r"DCNT(" + HEX + r")G(" + HEX + r")NM", s):
                    n = hx(m[1])
                    prop = re.search(r"P(" + HEX + r')U"([^"]*)"', s)
                    p = hx(prop[1]) if prop else 0
                    # OTF1 uses bits 2-3 for START/POINT/LAST/NEXT; OTF2
                    # uses bits 4-5. Preserve the original properties as well.
                    counters[n] = dict(
                        self=n,
                        name=text(quoted(s)),
                        description=text("OTF counter"),
                        unit=text(prop[2] if prop else ""),
                        metricMode=(p & 1) | ((p & 12) << 2),
                        valueType=4,
                        base=1,
                        exponent=0,
                        otfProperties=p,
                    )
                elif m := re.match(r"DCO(" + HEX + r")NM", s):
                    colls[hx(m[1])] = quoted(s)
    for n, (name, g, src) in functions.items():
        f, line = sources.get(src, (0, 0))
        defs.append(
            (
                "Region",
                dict(
                    self=n,
                    name=text(name),
                    groupName=func_groups.get(g, "Application"),
                    paradigm=4 if "MPI" in func_groups.get(g, "") else 1,
                    regionRole=1,
                    sourceFile=text(files.get(f, "")),
                    beginLineNumber=line,
                ),
            )
        )
    for n, d in counters.items():
        defs.extend(
            [("MetricMember", d), ("MetricClass", dict(self=n, metricMembers=[n]))]
        )
    defs.append(
        (
            "SystemTreeNode",
            dict(
                self=0,
                name=text("OTF trace"),
                className=text("machine"),
                parent=4294967295,
            ),
        )
    )
    yield dict(
        record="definition",
        kind="ClockProperties",
        data=dict(timerResolution=resolution, globalOffset=0, traceLength=0),
    )
    for kind, d in defs:
        yield dict(record="definition", kind=kind, data=d)

    def stream(p):
        tick = 0
        loc = 0
        attrs = []
        with gzip.open(p, "rt") if p.suffix == ".z" else open(p) as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                first = s[0]
                if first in "0123456789abcdef" and _TIME(s):
                    tick = int(s, 16)
                    continue
                if first == "*":
                    loc = hx(s[1:])
                    continue
                if first == "K":
                    attrs.append({"otf": s})
                    continue
                d = {"raw": s}
                kind = "Otf1Record"
                if first == "E" and (m := _ENTER(s)):
                    kind = "Enter"
                    d["region"] = int(m[1], 16)
                elif first == "L":
                    kind = "Leave"
                    m = _LEAVE(s)
                    d["region"] = int(m[1], 16) if m else None
                elif first == "C" and (m := _COUNTER(s)):
                    kind = "Metric"
                    d["metric"] = int(m[1], 16)
                    d["metricValues"] = [int(m[2], 16)]
                elif first in "SR" and (m := _MESSAGE(s)):
                    kind = "MpiSend" if m[1] == "S" else "MpiRecv"
                    d.update(
                        {
                            ("receiver" if m[1] == "S" else "sender"): hx(m[2]),
                            "msgLength": hx(m[3]),
                            "msgTag": hx(m[4]),
                            "communicator": hx(m[5]),
                            "otfPeer": True,
                        }
                    )
                    # OTF peer is a process token, not a communicator-local rank.
                elif first == "C" and (m := _COLLECTIVE(s)):
                    kind = "OtfCollective"
                    d.update(
                        operation=colls.get(hx(m[1]), m[1]),
                        communicator=hx(m[2]),
                        root=hx(m[3]),
                        sent=hx(m[4]),
                        received=hx(m[5]),
                        duration=hx(m[6]),
                    )
                elif first == "F" and (m := _FILE(s)):
                    kind = "OtfFileOperation"
                    d.update(
                        file=hx(m[1]),
                        handle=hx(m[2]),
                        operation={
                            0: "OPEN",
                            1: "CLOSE",
                            2: "READ",
                            3: "WRITE",
                            4: "SEEK",
                        }.get(hx(m[3]) & 31, m[3]),
                        bytes=hx(m[4]),
                        duration=hx(m[5]),
                    )
                elif first == "T":
                    kind = "OtfSnapshot"
                rec = {
                    "record": "event",
                    "kind": kind,
                    "location": loc,
                    "time": tick,
                    "data": d,
                }
                if attrs:
                    rec["attributes"] = attrs
                    attrs = []
                yield rec

    event_files = sorted(base.parent.glob(base.name + ".*.events")) + sorted(
        base.parent.glob(base.name + ".*.events.z")
    )
    if not event_files:
        raise ValueError("No OTF event streams found next to the anchor")
    yield from heapq.merge(*(stream(p) for p in event_files), key=lambda e: e["time"])
