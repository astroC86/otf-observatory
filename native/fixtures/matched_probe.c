/* Wire interoperability archive for the four matched-probe records (MpiProbe, MpiMrecv,
 * MpiImrecvRequest, MpiImrecv). Uses local communicator and attribute mappings, a clock
 * correction and integer extremes. It makes no claims about MPI execution semantics. */
#include "fixture.h"

enum { LOCAL_COMM = 0, GLOBAL_COMM = 20, LOCAL_ATTRIBUTE = 0, GLOBAL_ATTRIBUTE = 7 };

static void write_events(OTF2_Archive *archive) {
    CHECK(OTF2_Archive_OpenEvtFiles(archive));
    OTF2_EvtWriter *writer = OTF2_Archive_GetEvtWriter(archive, 0);
    OTF2_AttributeList *attributes = OTF2_AttributeList_New();
    CHECK(OTF2_AttributeList_AddUint64(attributes, LOCAL_ATTRIBUTE, UINT64_MAX));
    CHECK(OTF2_EvtWriter_MpiProbe(writer, attributes, 100, 0, LOCAL_COMM, UINT32_MAX, 0));
    CHECK(OTF2_EvtWriter_MpiMrecv(writer, NULL, 110, 0, UINT64_MAX));
    CHECK(OTF2_EvtWriter_MpiProbe(writer, NULL, 120, UINT32_MAX, LOCAL_COMM, 256, UINT64_MAX));
    CHECK(OTF2_EvtWriter_MpiImrecvRequest(writer, NULL, 130, UINT64_MAX, 256));
    CHECK(OTF2_EvtWriter_MpiImrecv(writer, NULL, 140, 256, 65536));
    CHECK(OTF2_EvtWriter_Enter(writer, NULL, 150, 0));
    CHECK(OTF2_EvtWriter_Leave(writer, NULL, 160, 0));
    OTF2_AttributeList_Delete(attributes);
    CHECK(OTF2_Archive_CloseEvtWriter(archive, writer));
    CHECK(OTF2_Archive_CloseEvtFiles(archive));
}

static void write_mapping(OTF2_DefWriter *writer, OTF2_MappingType type, uint64_t local,
                          uint64_t global) {
    OTF2_IdMap *map = OTF2_IdMap_Create(OTF2_ID_MAP_DENSE, 1);
    CHECK(OTF2_IdMap_AddIdPair(map, local, global));
    CHECK(OTF2_DefWriter_WriteMappingTable(writer, type, map));
    OTF2_IdMap_Free(map);
}

static void write_local_definitions(OTF2_Archive *archive) {
    CHECK(OTF2_Archive_OpenDefFiles(archive));
    OTF2_DefWriter *writer = OTF2_Archive_GetDefWriter(archive, 0);
    write_mapping(writer, OTF2_MAPPING_COMM, LOCAL_COMM, GLOBAL_COMM);
    write_mapping(writer, OTF2_MAPPING_ATTRIBUTE, LOCAL_ATTRIBUTE, GLOBAL_ATTRIBUTE);
    CHECK(OTF2_DefWriter_WriteClockOffset(writer, 100, 10, 0));
    CHECK(OTF2_DefWriter_WriteClockOffset(writer, 160, 10, 0));
    CHECK(OTF2_Archive_CloseDefWriter(archive, writer));
    CHECK(OTF2_Archive_CloseDefFiles(archive));
}

static void write_global_definitions(OTF2_Archive *archive) {
    OTF2_GlobalDefWriter *global = OTF2_Archive_GetGlobalDefWriter(archive);
    CHECK(OTF2_GlobalDefWriter_WriteClockProperties(global, 10, 100, 80, OTF2_UNDEFINED_TIMESTAMP));
    static const char *const strings[] = {"", "Fixture"};
    write_strings(global, strings, ARRAY_LENGTH(strings));
    CHECK(OTF2_GlobalDefWriter_WriteAttribute(global, GLOBAL_ATTRIBUTE, 1, 0, OTF2_TYPE_UINT64));
    CHECK(OTF2_GlobalDefWriter_WriteRegion(global, 0, 1, 0, 0, OTF2_REGION_ROLE_FUNCTION,
                                           OTF2_PARADIGM_USER, OTF2_REGION_FLAG_NONE, 0, 0, 0));
    CHECK(
        OTF2_GlobalDefWriter_WriteSystemTreeNode(global, 0, 1, 0, OTF2_UNDEFINED_SYSTEM_TREE_NODE));
    CHECK(OTF2_GlobalDefWriter_WriteLocationGroup(global, 0, 1, OTF2_LOCATION_GROUP_TYPE_PROCESS, 0,
                                                  OTF2_UNDEFINED_LOCATION_GROUP));
    CHECK(OTF2_GlobalDefWriter_WriteLocation(global, 0, 1, OTF2_LOCATION_TYPE_CPU_THREAD, 7, 0));
    static const uint64_t members[] = {0};
    CHECK(OTF2_GlobalDefWriter_WriteGroup(global, 0, 1, OTF2_GROUP_TYPE_COMM_LOCATIONS,
                                          OTF2_PARADIGM_MPI, OTF2_GROUP_FLAG_NONE, 1, members));
    CHECK(OTF2_GlobalDefWriter_WriteGroup(global, 1, 1, OTF2_GROUP_TYPE_COMM_GROUP,
                                          OTF2_PARADIGM_MPI, OTF2_GROUP_FLAG_NONE, 1, members));
    CHECK(OTF2_GlobalDefWriter_WriteComm(global, GLOBAL_COMM, 1, 1, OTF2_UNDEFINED_COMM,
                                         OTF2_COMM_FLAG_NONE));
}

int main(int argc, char **argv) {
    if (argc != 2) {
        return 1;
    }
    OTF2_Archive *archive = open_archive(argv[1], "fixture");
    write_events(archive);
    write_local_definitions(archive);
    write_global_definitions(archive);
    CHECK(OTF2_Archive_Close(archive));
    return 0;
}
