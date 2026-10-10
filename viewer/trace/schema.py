"""Importer-owned tables, indexes and cache version contracts."""

VERSION = 3
MESSAGE_INDEX_VERSION = 8
STATE_TRANSITION_PREDICATE = "kind IN ('CallingContextEnter','CallingContextLeave','CallingContextSample','ThreadBegin','ThreadTeamBegin')"
STATE_TRANSITION_INDEX = (
    "CREATE INDEX IF NOT EXISTS ev_state_transition ON events(location,id) WHERE "
    + STATE_TRANSITION_PREDICATE
)
METRIC_INDEX = "CREATE INDEX met ON metrics(metric,location,time,id,value,raw)"
MPI_MESSAGE_EVENTS = (
    "MpiSend",
    "MpiRecv",
    "MpiIsend",
    "MpiIsendComplete",
    "MpiIrecv",
    "MpiIrecvRequest",
    "MpiRequestCancelled",
)
STACK_EVENTS = frozenset(
    (
        "Enter",
        "Leave",
        "CallingContextEnter",
        "CallingContextLeave",
        "CallingContextSample",
        "OmpTaskCreate",
        "ThreadTaskCreate",
        "OmpTaskSwitch",
        "ThreadTaskSwitch",
        "OmpTaskComplete",
        "ThreadTaskComplete",
    )
)
SCHEMA = """
CREATE TABLE definitions(kind TEXT,ref TEXT,data TEXT);
CREATE TABLE events(id INTEGER PRIMARY KEY,location TEXT,time REAL,tick TEXT,kind TEXT,data TEXT);
CREATE TABLE paths(id INTEGER PRIMARY KEY,parent INTEGER,region TEXT,depth INTEGER);
CREATE TABLE spans(id INTEGER PRIMARY KEY,location TEXT,region TEXT,start REAL,end REAL,depth INTEGER,parent INTEGER,path INTEGER,exclusive REAL,incomplete INTEGER,sampled INTEGER,continuation INTEGER DEFAULT 0,invocation INTEGER);
CREATE TABLE slices(id INTEGER PRIMARY KEY,location TEXT,region TEXT,path INTEGER,start REAL,end REAL,span INTEGER);
CREATE TABLE metrics(id INTEGER PRIMARY KEY,location TEXT,metric TEXT,time REAL,value REAL,raw TEXT);
CREATE TABLE messages(id INTEGER PRIMARY KEY,source TEXT,target TEXT,start REAL,end REAL,comm TEXT,tag TEXT,bytes INTEGER,status TEXT,send_event INTEGER,recv_event INTEGER);
CREATE TABLE message_evidence(send_event INTEGER PRIMARY KEY,recv_event INTEGER,native_start REAL,native_end REAL,emitter TEXT,corrected INTEGER,emission_event INTEGER);
CREATE TABLE collectives(id INTEGER PRIMARY KEY,location TEXT,start REAL,end REAL,operation TEXT,comm TEXT,root TEXT,sent INTEGER,received INTEGER,event INTEGER);
CREATE TABLE io(id INTEGER PRIMARY KEY,location TEXT,start REAL,end REAL,handle TEXT,file TEXT,operation TEXT,bytes INTEGER,status TEXT,event INTEGER);
CREATE TABLE rma(id INTEGER PRIMARY KEY,location TEXT,target TEXT,start REAL,end REAL,operation TEXT,win TEXT,bytes INTEGER,status TEXT,event INTEGER);
CREATE TABLE rma_evidence(begin_event INTEGER PRIMARY KEY,completion_event INTEGER,completion_location TEXT,scope TEXT,native_source TEXT,native_target TEXT,matching_id TEXT,completion_kind TEXT);
CREATE TABLE markers(id INTEGER PRIMARY KEY,time REAL,duration REAL,location TEXT,name TEXT,category TEXT,severity TEXT,data TEXT);
CREATE TABLE samples(id INTEGER PRIMARY KEY,location TEXT,time REAL,path INTEGER,context TEXT);
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
"""
# R-tree interval indexes and their source tables. An R-tree's content depends
# on insertion order: fills read the source table in rowid order.
INTERVAL_INDEXES = (("span_time", "spans"), ("slice_time", "slices"))
INTERVAL_INDEX = "CREATE VIRTUAL TABLE {} USING rtree(id,start,end);\n"
INTERVAL_FILL = "INSERT INTO {} SELECT id,start,end FROM {};\n"
# Every index object, in sqlite_master order; INDEXES then fills the R-trees.
INDEX_OBJECTS = (
    f"""
CREATE INDEX ev_time ON events(time); CREATE INDEX ev_loc ON events(location,time); CREATE INDEX ev_kind ON events(kind,time);
CREATE INDEX sp_loc ON spans(location,start); CREATE INDEX sp_reg ON spans(region,start);
CREATE INDEX sl_loc ON slices(location,start); CREATE INDEX sl_reg ON slices(region,start);
{METRIC_INDEX}; CREATE INDEX msg_time ON messages(start); CREATE INDEX coll_time ON collectives(start);
CREATE INDEX IF NOT EXISTS coll_event ON collectives(event);
"""
    + "".join(INTERVAL_INDEX.format(rtree) for rtree, _ in INTERVAL_INDEXES)
    + "CREATE INDEX def_kind ON definitions(kind,ref);\n"
    + STATE_TRANSITION_INDEX
    + ";\n"
)
INDEXES = INDEX_OBJECTS + "".join(
    INTERVAL_FILL.format(rtree, table) for rtree, table in INTERVAL_INDEXES
)
