/* OpenMP task lifecycle through the real task records: `tasks <archive-dir> modern|legacy`.
 *
 * "modern" writes ThreadTeam/ThreadTask records, "legacy" writes OmpTask records; the OTF2
 * writer documentation forbids mixing the two families in one archive. Both record task
 * creation, switching, completion and TASK_WAIT regions, not task data dependences.
 */
#include "fixture.h"
#include <string.h>

/* The legacy archive deliberately uses the deprecated OmpTask writer API. */
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"

enum operation { TEAM_BEGIN, TEAM_END, CREATE, SWITCH, COMPLETE, ENTER, LEAVE };
enum task { PARENT, CHILD, HELPER };
enum region { UNTIED_PARENT = 10, TASK_WAIT, UNTIED_CHILD, HELPER_TASK, TASK_CREATE };

struct record {
    unsigned location; /* index into LOCATIONS */
    unsigned tick;
    enum operation operation;
    unsigned value; /* task for task operations, region for ENTER/LEAVE */
};

static const OTF2_LocationRef LOCATIONS[] = {100, 101, 200, 201};
static const struct record RECORDS[] = {
    {0, 0, TEAM_BEGIN, 0},
    {1, 1, TEAM_BEGIN, 0},
    {2, 2, TEAM_BEGIN, 0},
    {3, 3, TEAM_BEGIN, 0},
    /* The helper is not a child of the waiting parent. */
    {1, 40, ENTER, TASK_CREATE},
    {1, 50, CREATE, HELPER},
    {1, 60, LEAVE, TASK_CREATE},
    {0, 80, ENTER, TASK_CREATE},
    {0, 100, CREATE, PARENT},
    {2, 105, ENTER, TASK_CREATE},
    {0, 110, LEAVE, TASK_CREATE},
    {2, 125, CREATE, PARENT},
    {2, 135, LEAVE, TASK_CREATE},
    {0, 200, SWITCH, PARENT},
    {2, 225, SWITCH, PARENT},
    {0, 300, ENTER, UNTIED_PARENT},
    {2, 325, ENTER, UNTIED_PARENT},
    {0, 380, ENTER, TASK_CREATE},
    {0, 400, CREATE, CHILD},
    {2, 405, ENTER, TASK_CREATE},
    {0, 410, LEAVE, TASK_CREATE},
    {2, 425, CREATE, CHILD},
    {2, 435, LEAVE, TASK_CREATE},
    {0, 600, ENTER, TASK_WAIT},
    {2, 625, ENTER, TASK_WAIT},
    {0, 700, SWITCH, CHILD},
    {3, 725, SWITCH, CHILD},
    {0, 800, ENTER, UNTIED_CHILD},
    {3, 825, ENTER, UNTIED_CHILD},
    {0, 900, SWITCH, HELPER},
    {0, 1000, ENTER, HELPER_TASK},
    {1, 1100, SWITCH, CHILD},
    {1, 1200, LEAVE, UNTIED_CHILD},
    {3, 1225, LEAVE, UNTIED_CHILD},
    {1, 1300, COMPLETE, CHILD},
    {3, 1325, COMPLETE, CHILD},
    {1, 1400, SWITCH, PARENT},
    {1, 1500, LEAVE, TASK_WAIT},
    {2, 1525, LEAVE, TASK_WAIT},
    {1, 1600, LEAVE, UNTIED_PARENT},
    {2, 1625, LEAVE, UNTIED_PARENT},
    {1, 1700, COMPLETE, PARENT},
    {2, 1725, COMPLETE, PARENT},
    {0, 1800, LEAVE, HELPER_TASK},
    {0, 1900, COMPLETE, HELPER},
    {0, 2100, TEAM_END, 0},
    {1, 2110, TEAM_END, 0},
    {2, 2120, TEAM_END, 0},
    {3, 2130, TEAM_END, 0},
};

static void write_record(OTF2_EvtWriter *writer, const struct record *r, int modern) {
    OTF2_TimeStamp time = 10000 + r->tick;
    OTF2_CommRef team = r->location % 2 ? 7 : 0; /* local team ids, mapped per location */
    uint32_t creator = r->value == HELPER ? 1 : 0;
    uint32_t generation = r->value == PARENT  ? UINT32_MAX - 1
                          : r->value == CHILD ? UINT32_MAX
                                              : UINT32_MAX - 2;
    uint64_t task_id = r->value == PARENT  ? UINT64_MAX - 3
                       : r->value == CHILD ? UINT64_MAX - 2
                                           : UINT64_MAX - 4;
    switch (r->operation) {
    case TEAM_BEGIN:
        if (modern) {
            CHECK(OTF2_EvtWriter_ThreadTeamBegin(writer, NULL, time, team));
        }
        break;
    case TEAM_END:
        if (modern) {
            CHECK(OTF2_EvtWriter_ThreadTeamEnd(writer, NULL, time, team));
        }
        break;
    case ENTER:
        CHECK(OTF2_EvtWriter_Enter(writer, NULL, time, r->value));
        break;
    case LEAVE:
        CHECK(OTF2_EvtWriter_Leave(writer, NULL, time, r->value));
        break;
    case CREATE:
        if (modern) {
            CHECK(OTF2_EvtWriter_ThreadTaskCreate(writer, NULL, time, team, creator, generation));
        } else {
            CHECK(OTF2_EvtWriter_OmpTaskCreate(writer, NULL, time, task_id));
        }
        break;
    case SWITCH:
        if (modern) {
            CHECK(OTF2_EvtWriter_ThreadTaskSwitch(writer, NULL, time, team, creator, generation));
        } else {
            CHECK(OTF2_EvtWriter_OmpTaskSwitch(writer, NULL, time, task_id));
        }
        break;
    case COMPLETE:
        if (modern) {
            CHECK(OTF2_EvtWriter_ThreadTaskComplete(writer, NULL, time, team, creator, generation));
        } else {
            CHECK(OTF2_EvtWriter_OmpTaskComplete(writer, NULL, time, task_id));
        }
        break;
    }
}

/* Writes all records and returns each location's event count. */
static void write_events(OTF2_Archive *archive, int modern, uint64_t counts[]) {
    CHECK(OTF2_Archive_OpenEvtFiles(archive));
    OTF2_EvtWriter *writers[ARRAY_LENGTH(LOCATIONS)];
    for (size_t i = 0; i < ARRAY_LENGTH(LOCATIONS); i++) {
        writers[i] = OTF2_Archive_GetEvtWriter(archive, LOCATIONS[i]);
    }
    for (size_t i = 0; i < ARRAY_LENGTH(RECORDS); i++) {
        write_record(writers[RECORDS[i].location], &RECORDS[i], modern);
    }
    for (size_t i = 0; i < ARRAY_LENGTH(LOCATIONS); i++) {
        CHECK(OTF2_EvtWriter_GetNumberOfEvents(writers[i], &counts[i]));
        CHECK(OTF2_Archive_CloseEvtWriter(archive, writers[i]));
    }
    CHECK(OTF2_Archive_CloseEvtFiles(archive));
}

/* Modern archives map each location's local team id (0 or 7) to its global team. */
static void write_local_definitions(OTF2_Archive *archive, int modern) {
    CHECK(OTF2_Archive_OpenDefFiles(archive));
    for (size_t i = 0; i < ARRAY_LENGTH(LOCATIONS); i++) {
        OTF2_DefWriter *writer = OTF2_Archive_GetDefWriter(archive, LOCATIONS[i]);
        if (modern) {
            OTF2_IdMap *teams = OTF2_IdMap_Create(OTF2_ID_MAP_SPARSE, 1);
            CHECK(OTF2_IdMap_AddIdPair(teams, i % 2 ? 7 : 0,
                                       i < 2 ? UINT32_MAX - 2 : UINT32_MAX - 1));
            CHECK(OTF2_DefWriter_WriteMappingTable(writer, OTF2_MAPPING_COMM, teams));
            OTF2_IdMap_Free(teams);
        }
        CHECK(OTF2_Archive_CloseDefWriter(archive, writer));
    }
    CHECK(OTF2_Archive_CloseDefFiles(archive));
}

static void write_global_definitions(OTF2_Archive *archive, int modern, const uint64_t counts[]) {
    OTF2_GlobalDefWriter *global = OTF2_Archive_GetGlobalDefWriter(archive);
    CHECK(OTF2_GlobalDefWriter_WriteClockProperties(global, 100, 10000, 2400,
                                                    OTF2_UNDEFINED_TIMESTAMP));
    static const char *const strings[] = {"",
                                          "Task callback fixture",
                                          "process A",
                                          "process B",
                                          "thread",
                                          "Untied parent",
                                          "Task wait",
                                          "Untied child",
                                          "Helper task",
                                          "Task create"};
    write_strings(global, strings, ARRAY_LENGTH(strings));
    CHECK(
        OTF2_GlobalDefWriter_WriteSystemTreeNode(global, 0, 1, 0, OTF2_UNDEFINED_SYSTEM_TREE_NODE));
    CHECK(OTF2_GlobalDefWriter_WriteLocationGroup(global, 10, 2, OTF2_LOCATION_GROUP_TYPE_PROCESS,
                                                  0, OTF2_UNDEFINED_LOCATION_GROUP));
    /* Legacy archives spawn process B: a different task scope from its creator. */
    if (!modern) {
        CHECK(OTF2_GlobalDefWriter_WriteLocationGroup(global, 20, 3,
                                                      OTF2_LOCATION_GROUP_TYPE_PROCESS, 0, 10));
    }
    for (size_t i = 0; i < ARRAY_LENGTH(LOCATIONS); i++) {
        CHECK(OTF2_GlobalDefWriter_WriteLocation(global, LOCATIONS[i], 4,
                                                 OTF2_LOCATION_TYPE_CPU_THREAD, counts[i],
                                                 modern || i < 2 ? 10 : 20));
    }
    static const OTF2_RegionRole roles[] = {
        OTF2_REGION_ROLE_TASK_UNTIED, OTF2_REGION_ROLE_TASK_WAIT, OTF2_REGION_ROLE_TASK_UNTIED,
        OTF2_REGION_ROLE_TASK, OTF2_REGION_ROLE_TASK_CREATE};
    for (uint32_t i = 0; i < ARRAY_LENGTH(roles); i++) {
        CHECK(OTF2_GlobalDefWriter_WriteRegion(global, UNTIED_PARENT + i, 5 + i, 0, 0, roles[i],
                                               OTF2_PARADIGM_OPENMP, OTF2_REGION_FLAG_NONE, 0, 0,
                                               0));
    }
    if (modern) {
        /* Two teams: locations 100/101 and 200/201. */
        static const uint64_t first[] = {0, 1}, second[] = {2, 3};
        CHECK(OTF2_GlobalDefWriter_WriteGroup(global, 100, 1, OTF2_GROUP_TYPE_COMM_LOCATIONS,
                                              OTF2_PARADIGM_OPENMP, OTF2_GROUP_FLAG_NONE, 4,
                                              LOCATIONS));
        CHECK(OTF2_GlobalDefWriter_WriteGroup(global, 101, 1, OTF2_GROUP_TYPE_COMM_GROUP,
                                              OTF2_PARADIGM_OPENMP, OTF2_GROUP_FLAG_NONE, 2,
                                              first));
        CHECK(OTF2_GlobalDefWriter_WriteGroup(global, 102, 1, OTF2_GROUP_TYPE_COMM_GROUP,
                                              OTF2_PARADIGM_OPENMP, OTF2_GROUP_FLAG_NONE, 2,
                                              second));
        CHECK(OTF2_GlobalDefWriter_WriteComm(global, UINT32_MAX - 2, 1, 101, OTF2_UNDEFINED_COMM,
                                             OTF2_COMM_FLAG_NONE));
        CHECK(OTF2_GlobalDefWriter_WriteComm(global, UINT32_MAX - 1, 1, 102, OTF2_UNDEFINED_COMM,
                                             OTF2_COMM_FLAG_NONE));
    }
}

int main(int argc, char **argv) {
    if (argc != 3 || (strcmp(argv[2], "modern") && strcmp(argv[2], "legacy"))) {
        return 1;
    }
    int modern = !strcmp(argv[2], "modern");
    OTF2_Archive *archive = open_archive(argv[1], "tasks");
    uint64_t counts[ARRAY_LENGTH(LOCATIONS)];
    write_events(archive, modern, counts);
    write_local_definitions(archive, modern);
    write_global_definitions(archive, modern, counts);
    CHECK(OTF2_Archive_Close(archive));
    return 0;
}
