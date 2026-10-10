/* Inter-communicator collectives between group A (locations 0, 1) and group B (2, 3, 4):
 * a rooted MPI_Bcast, a nonblocking MPI_Iallreduce completed in MPI_Waitall, and a barrier. */
#include "fixture.h"

enum { LOCATIONS = 5 };
enum { BCAST, IALLREDUCE, WAITALL, BARRIER }; /* region ids */

static void write_location_events(OTF2_EvtWriter *writer, uint64_t location) {
    /* Broadcast rooted at location 1 of group A; group B receives 4 bytes each. */
    uint64_t start = location == 0 ? 2 : location == 1 ? 50 : 10 + location;
    uint64_t end = location == 0 ? 3 : 80;
    uint32_t root = location == 0   ? OTF2_COLLECTIVE_ROOT_THIS_GROUP
                    : location == 1 ? OTF2_COLLECTIVE_ROOT_SELF
                                    : 1;
    CHECK(OTF2_EvtWriter_Enter(writer, NULL, start - 1, BCAST));
    CHECK(OTF2_EvtWriter_MpiCollectiveBegin(writer, NULL, start));
    CHECK(OTF2_EvtWriter_MpiCollectiveEnd(writer, NULL, end, OTF2_COLLECTIVE_OP_BCAST, 0, root,
                                          location == 1 ? 12 : 0, location >= 2 ? 4 : 0));
    CHECK(OTF2_EvtWriter_Leave(writer, NULL, end + 1, BCAST));

    /* Nonblocking allreduce: request in MPI_Iallreduce, completion inside MPI_Waitall. */
    start = 100 + 10 * location;
    uint64_t wait = start + 2 > 120 ? start + 2 : 120;
    uint64_t bytes = location < 2 ? 12 : 8;
    CHECK(OTF2_EvtWriter_Enter(writer, NULL, start - 1, IALLREDUCE));
    CHECK(OTF2_EvtWriter_NonBlockingCollectiveRequest(writer, NULL, start, 1));
    CHECK(OTF2_EvtWriter_Leave(writer, NULL, start + 1, IALLREDUCE));
    CHECK(OTF2_EvtWriter_Enter(writer, NULL, wait, WAITALL));
    CHECK(OTF2_EvtWriter_NonBlockingCollectiveComplete(writer, NULL, 160 + location,
                                                       OTF2_COLLECTIVE_OP_ALLREDUCE, 0,
                                                       OTF2_COLLECTIVE_ROOT_NONE, bytes, bytes, 1));
    CHECK(OTF2_EvtWriter_Leave(writer, NULL, 170, WAITALL));

    /* Barrier that location 1 enters last. */
    start = location == 1 ? 280 : 200 + location * 10;
    end = location == 0 ? 260 : 300;
    CHECK(OTF2_EvtWriter_Enter(writer, NULL, start - 1, BARRIER));
    CHECK(OTF2_EvtWriter_MpiCollectiveBegin(writer, NULL, start));
    CHECK(OTF2_EvtWriter_MpiCollectiveEnd(writer, NULL, end, OTF2_COLLECTIVE_OP_BARRIER, 0,
                                          OTF2_COLLECTIVE_ROOT_NONE, 0, 0));
    CHECK(OTF2_EvtWriter_Leave(writer, NULL, end + 1, BARRIER));
}

static void write_events(OTF2_Archive *archive) {
    CHECK(OTF2_Archive_OpenEvtFiles(archive));
    for (uint64_t location = 0; location < LOCATIONS; location++) {
        OTF2_EvtWriter *writer = OTF2_Archive_GetEvtWriter(archive, location);
        write_location_events(writer, location);
        CHECK(OTF2_Archive_CloseEvtWriter(archive, writer));
    }
    CHECK(OTF2_Archive_CloseEvtFiles(archive));
}

static void write_global_definitions(OTF2_Archive *archive) {
    OTF2_GlobalDefWriter *global = OTF2_Archive_GetGlobalDefWriter(archive);
    CHECK(OTF2_GlobalDefWriter_WriteClockProperties(global, 10, 0, 400, OTF2_UNDEFINED_TIMESTAMP));
    static const char *const strings[] = {
        "", "MPI_Bcast", "MPI_Iallreduce", "MPI_Waitall", "MPI_Barrier", "intercomm fixture"};
    write_strings(global, strings, ARRAY_LENGTH(strings));
    CHECK(
        OTF2_GlobalDefWriter_WriteSystemTreeNode(global, 0, 5, 0, OTF2_UNDEFINED_SYSTEM_TREE_NODE));
    for (uint64_t location = 0; location < LOCATIONS; location++) {
        CHECK(OTF2_GlobalDefWriter_WriteLocationGroup(global, location, 5,
                                                      OTF2_LOCATION_GROUP_TYPE_PROCESS, 0,
                                                      OTF2_UNDEFINED_LOCATION_GROUP));
        CHECK(OTF2_GlobalDefWriter_WriteLocation(global, location, 5, OTF2_LOCATION_TYPE_CPU_THREAD,
                                                 14, location));
    }
    for (uint32_t region = BCAST; region <= BARRIER; region++) {
        CHECK(OTF2_GlobalDefWriter_WriteRegion(global, region, region + 1, region + 1, 0,
                                               OTF2_REGION_ROLE_FUNCTION, OTF2_PARADIGM_MPI,
                                               OTF2_REGION_FLAG_NONE, OTF2_UNDEFINED_STRING, 0, 0));
    }
    static const uint64_t world[] = {0, 1, 2, 3, 4}, group_a[] = {0, 1}, group_b[] = {2, 3, 4};
    CHECK(OTF2_GlobalDefWriter_WriteGroup(global, 0, 5, OTF2_GROUP_TYPE_COMM_LOCATIONS,
                                          OTF2_PARADIGM_MPI, OTF2_GROUP_FLAG_NONE, 5, world));
    CHECK(OTF2_GlobalDefWriter_WriteGroup(global, 1, 5, OTF2_GROUP_TYPE_COMM_GROUP,
                                          OTF2_PARADIGM_MPI, OTF2_GROUP_FLAG_NONE, 2, group_a));
    CHECK(OTF2_GlobalDefWriter_WriteGroup(global, 2, 5, OTF2_GROUP_TYPE_COMM_GROUP,
                                          OTF2_PARADIGM_MPI, OTF2_GROUP_FLAG_NONE, 3, group_b));
    CHECK(OTF2_GlobalDefWriter_WriteInterComm(global, 0, 5, 1, 2, OTF2_UNDEFINED_COMM,
                                              OTF2_COMM_FLAG_NONE));
}

int main(int argc, char **argv) {
    if (argc != 2) {
        return 1;
    }
    OTF2_Archive *archive = open_archive(argv[1], "intercomm");
    CHECK(OTF2_Archive_SetCreator(archive, "OTF2 viewer intercommunicator fixture"));
    write_events(archive);
    static const OTF2_LocationRef locations[] = {0, 1, 2, 3, 4};
    write_empty_local_definitions(archive, locations, ARRAY_LENGTH(locations));
    write_global_definitions(archive);
    CHECK(OTF2_Archive_Close(archive));
    return 0;
}
