"""Raw event, definition, operation, marker, and span inspection queries."""

import json
import pathlib

from .encoding import dumps

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIELD_SCHEMA = (
    json.loads((ROOT / "native/build/schema.json").read_text())
    if (ROOT / "native/build/schema.json").exists()
    else {}
)


class EventQueries:
    def operations(self, q, table):
        start, end, where, args = self.scope(q, regions=False)
        where = (
            "start<? AND (coalesce(end,start)>? OR (coalesce(end,start)=start AND start>=?))"
            + where
        )
        args = [end, start, start] + args
        if table not in ("collectives", "io", "rma"):
            raise ValueError("Invalid operation type")
        rows = self.rows(
            f"SELECT * FROM {table} WHERE {where} ORDER BY start LIMIT 3000", args
        )
        field = "file,operation" if table == "io" else "operation"
        stats = self.rows(
            f'SELECT {field},COUNT(*) count,SUM(max(0,min(coalesce(end,start),?)-max(start,?))) duration,SUM({"sent" if table=="collectives" else "bytes"}) bytes'
            + (",SUM(received) received" if table == "collectives" else "")
            + f" FROM {table} WHERE {where} GROUP BY {field}",
            [end, start] + args,
        )
        return dict(rows=rows, summary=stats, total=sum(r["count"] for r in stats))

    def events(self, q):
        start, end, where, args = self.scope(q, regions=False)
        where = "time>=? AND time<=?" + where
        args = [start, end] + args
        if q.get("kind"):
            where += " AND kind=?"
            args.append(q["kind"])
        if q.get("search"):
            where += " AND (data LIKE ? OR kind LIKE ?)"
            args += ["%" + q["search"] + "%"] * 2
        offset = max(0, int(q.get("offset", 0)))
        limit = min(1000, max(1, int(q.get("limit", 200))))
        rows = self.rows(
            f"SELECT * FROM events WHERE {where} ORDER BY time,id LIMIT ? OFFSET ?",
            args + [limit + 1, offset],
        )
        more = len(rows) > limit
        rows = rows[:limit]
        for r in rows:
            r["rawData"] = json.loads(r["data"])
            r["data"] = self.resolve(r["rawData"], r["kind"])
        return dict(rows=rows, more=more, offset=offset)

    def resolve(self, d, kind, definition=False):
        schema = FIELD_SCHEMA.get(
            ("GlobalDef:" if definition else "GlobalEvt:") + kind, {}
        )
        out = dict(d)
        for key, value in d.items():
            typ = schema.get(key, "").replace("OTF2_", "").replace("Ref", "")
            if typ in self.defs and str(value) in self.defs[typ]:
                v = self.defs[typ][str(value)]
                name = (
                    v.get("string")
                    if typ == "String"
                    else self.defs["String"].get(str(v.get("name")), {}).get("string")
                )
                if name is not None:
                    out[key] = {"ref": str(value), "name": name}
        return out

    def definitions(self, q):
        kind = q.get("kind", "")
        search = q.get("search", "").casefold()
        out = []
        for k, defs in self.defs.items():
            if kind and kind != k:
                continue
            for ident, d in defs.items():
                resolved = self.resolve(d, k, True)
                if search and search not in dumps(resolved).casefold():
                    continue
                out.append(dict(kind=k, id=ident, data=resolved, rawData=d))
        offset = max(0, int(q.get("offset", 0)))
        return dict(
            kinds=list(self.defs), rows=out[offset : offset + 300], total=len(out)
        )

    def span(self, ident):
        r = self.rows("SELECT * FROM spans WHERE id=?", (ident,))
        if not r:
            raise ValueError("Span not found")
        row = r[0]
        row["regionDefinition"] = self.regions.get(row["region"])
        row["events"] = self.rows(
            "SELECT id,kind,time,tick,data FROM events WHERE location=? AND time>=? AND time<=? ORDER BY time,id LIMIT 100",
            (row["location"], row["start"], row["end"]),
        )
        for e in row["events"]:
            e["rawData"] = json.loads(e["data"])
            e["data"] = self.resolve(e["rawData"], e["kind"])
        return row

    def markers(self, q):
        start, end, _, _ = self.scope(q, regions=False)
        if start == end:
            return []
        where = "time<=? AND time+coalesce(duration,0)>=?"
        args = [end, start]
        if q.get("locations"):
            ids = q["locations"].split(",")
            where += (
                " AND (location IS NULL OR location IN ("
                + ",".join("?" for _ in ids)
                + "))"
            )
            args += ids
        return self.rows(
            "SELECT * FROM markers WHERE " + where + " ORDER BY time", args
        )
