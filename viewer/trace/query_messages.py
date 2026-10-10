"""Raw MPI message selection, matrix, histogram, and row queries."""


class MessageQueries:
    def message_scope(self, q):
        start, end, _, _ = self.scope(q, regions=False)
        if start == end:
            return "0", []
        low = "min(coalesce(start,end),coalesce(end,start))"
        high = "max(coalesce(start,end),coalesce(end,start))"
        where = f"{low}<? AND ({high}>? OR ({low}={high} AND {low}>=?))"
        args = [end, start, start]
        if q.get("locations"):
            ids = q["locations"].split(",")
            marks = ",".join("?" for _ in ids)
            where += f" AND (source IN ({marks}) OR target IN ({marks}))"
            args += ids + ids
        for field in ("tag", "comm", "status"):
            if q.get(field):
                where += f" AND {field}=?"
                args.append(q[field])
        for field, op in [("minBytes", ">="), ("maxBytes", "<=")]:
            if q.get(field):
                where += f" AND bytes{op}?"
                args.append(int(q[field]))
        return where, args

    def messages(self, q):
        where, args = self.message_scope(q)
        group = {
            "size": "bytes",
            "tag": "tag",
            "communicator": "comm",
            "status": "status",
        }.get(q.get("by", "size"), "bytes")
        offset = max(0, int(q.get("offset", 0)))
        matrix, histogram, rows = self.rows_many(
            (
                f"""SELECT source,target,COUNT(*) count,SUM(bytes) bytes,AVG(CASE WHEN end>=start THEN end-start END) duration,
            MIN(CASE WHEN end>=start THEN end-start END) minimum,MAX(CASE WHEN end>=start THEN end-start END) maximum,
            SUM(CASE WHEN status='matched' THEN 1 ELSE 0 END) matched FROM messages WHERE {where} GROUP BY source,target""",
                args,
            ),
            (
                f"SELECT {group} label,COUNT(*) count,SUM(bytes) bytes,AVG(CASE WHEN end>=start THEN end-start END) duration FROM messages WHERE {where} GROUP BY {group} ORDER BY bytes DESC",
                args,
            ),
            (
                f"SELECT *,CASE WHEN end>start THEN bytes/(end-start) END bandwidth FROM messages WHERE {where} ORDER BY coalesce(start,end) LIMIT 500 OFFSET ?",
                args + [offset],
            ),
        )
        return dict(
            matrix=matrix,
            histogram=histogram,
            rows=rows,
            total=sum(r["count"] for r in matrix),
        )
