/* OTF2 group type 7 (COMM_LOCATION_GROUPS): communicator ranks refer to location groups
 * (processes), not locations. Rank 0 sends to rank 1, each from its process's second thread. */
#include "fixture.h"

static const OTF2_LocationRef LOCATIONS[] = {100, 101, 900, 901};
enum { PROCESS_0 = 9, PROCESS_1 = 100 }; /* location group ids */

static void write_events(OTF2_Archive *archive) {
    CHECK(OTF2_Archive_OpenEvtFiles(archive));
    for (size_t i = 0; i < ARRAY_LENGTH(LOCATIONS); i++) {
        OTF2_EvtWriter *writer = OTF2_Archive_GetEvtWriter(archive, LOCATIONS[i]);
        if (i == 1) {
            CHECK(OTF2_EvtWriter_MpiSend(writer, NULL, 10, 1, 0, 7, 64));
        }
        if (i == 3) {
            CHECK(OTF2_EvtWriter_MpiRecv(writer, NULL, 20, 0, 0, 7, 64));
        }
        CHECK(OTF2_Archive_CloseEvtWriter(archive, writer));
    }
    CHECK(OTF2_Archive_CloseEvtFiles(archive));
}

static void write_global_definitions(OTF2_Archive *archive) {
    OTF2_GlobalDefWriter *global = OTF2_Archive_GetGlobalDefWriter(archive);
    CHECK(OTF2_GlobalDefWriter_WriteClockProperties(global, 10, 0, 30, OTF2_UNDEFINED_TIMESTAMP));
    static const char *const strings[] = {"", "Fixture"};
    write_strings(global, strings, ARRAY_LENGTH(strings));
    CHECK(
        OTF2_GlobalDefWriter_WriteSystemTreeNode(global, 0, 1, 0, OTF2_UNDEFINED_SYSTEM_TREE_NODE));
    CHECK(OTF2_GlobalDefWriter_WriteLocationGroup(
        global, PROCESS_0, 1, OTF2_LOCATION_GROUP_TYPE_PROCESS, 0, OTF2_UNDEFINED_LOCATION_GROUP));
    CHECK(OTF2_GlobalDefWriter_WriteLocationGroup(
        global, PROCESS_1, 1, OTF2_LOCATION_GROUP_TYPE_PROCESS, 0, OTF2_UNDEFINED_LOCATION_GROUP));
    for (size_t i = 0; i < ARRAY_LENGTH(LOCATIONS); i++) {
        CHECK(OTF2_GlobalDefWriter_WriteLocation(global, LOCATIONS[i], 1,
                                                 OTF2_LOCATION_TYPE_CPU_THREAD, i % 2,
                                                 i < 2 ? PROCESS_0 : PROCESS_1));
    }
    static const uint64_t processes[] = {PROCESS_0, PROCESS_1}, ranks[] = {0, 1};
    CHECK(OTF2_GlobalDefWriter_WriteGroup(global, 0, 1, (OTF2_GroupType)7, OTF2_PARADIGM_MPI,
                                          OTF2_GROUP_FLAG_NONE, 2, processes));
    CHECK(OTF2_GlobalDefWriter_WriteGroup(global, 1, 1, OTF2_GROUP_TYPE_COMM_GROUP,
                                          OTF2_PARADIGM_MPI, OTF2_GROUP_FLAG_NONE, 2, ranks));
    CHECK(
        OTF2_GlobalDefWriter_WriteComm(global, 0, 1, 1, OTF2_UNDEFINED_COMM, OTF2_COMM_FLAG_NONE));
}

int main(int argc, char **argv) {
    if (argc != 2) {
        return 1;
    }
    OTF2_Archive *archive = open_archive(argv[1], "fixture");
    write_events(archive);
    write_empty_local_definitions(archive, LOCATIONS, ARRAY_LENGTH(LOCATIONS));
    write_global_definitions(archive);
    CHECK(OTF2_Archive_Close(archive));
    return 0;
}
