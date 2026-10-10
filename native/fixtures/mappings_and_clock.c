/* Basic interoperability archive: a location id above 2^53, a local region id that is
 * remapped to its global id, and a linear clock correction. */
#include "fixture.h"

static const OTF2_LocationRef LOCATION = UINT64_C(9007199254740993); /* 2^53 + 1 */

static void write_events(OTF2_Archive *archive) {
    CHECK(OTF2_Archive_OpenEvtFiles(archive));
    OTF2_EvtWriter *writer = OTF2_Archive_GetEvtWriter(archive, LOCATION);
    CHECK(OTF2_EvtWriter_Enter(writer, NULL, 100, 0)); /* local region 0 */
    CHECK(OTF2_EvtWriter_Leave(writer, NULL, 130, 0));
    CHECK(OTF2_Archive_CloseEvtWriter(archive, writer));
    CHECK(OTF2_Archive_CloseEvtFiles(archive));
}

static void write_local_definitions(OTF2_Archive *archive) {
    CHECK(OTF2_Archive_OpenDefFiles(archive));
    OTF2_DefWriter *writer = OTF2_Archive_GetDefWriter(archive, LOCATION);
    OTF2_IdMap *regions = OTF2_IdMap_Create(OTF2_ID_MAP_DENSE, 1);
    CHECK(OTF2_IdMap_AddIdPair(regions, 0, 20)); /* local region 0 is global region 20 */
    CHECK(OTF2_DefWriter_WriteMappingTable(writer, OTF2_MAPPING_REGION, regions));
    OTF2_IdMap_Free(regions);
    CHECK(OTF2_DefWriter_WriteClockOffset(writer, 100, 10, 0));
    CHECK(OTF2_DefWriter_WriteClockOffset(writer, 130, 10, 0));
    CHECK(OTF2_Archive_CloseDefWriter(archive, writer));
    CHECK(OTF2_Archive_CloseDefFiles(archive));
}

static void write_global_definitions(OTF2_Archive *archive) {
    OTF2_GlobalDefWriter *global = OTF2_Archive_GetGlobalDefWriter(archive);
    CHECK(OTF2_GlobalDefWriter_WriteClockProperties(global, 10, 100, 40, OTF2_UNDEFINED_TIMESTAMP));
    static const char *const strings[] = {"", "Fixture"};
    write_strings(global, strings, ARRAY_LENGTH(strings));
    CHECK(OTF2_GlobalDefWriter_WriteRegion(global, 20, 1, 0, 0, OTF2_REGION_ROLE_FUNCTION,
                                           OTF2_PARADIGM_USER, OTF2_REGION_FLAG_NONE, 0, 0, 0));
    CHECK(
        OTF2_GlobalDefWriter_WriteSystemTreeNode(global, 0, 1, 0, OTF2_UNDEFINED_SYSTEM_TREE_NODE));
    CHECK(OTF2_GlobalDefWriter_WriteLocationGroup(global, 0, 1, OTF2_LOCATION_GROUP_TYPE_PROCESS, 0,
                                                  OTF2_UNDEFINED_LOCATION_GROUP));
    CHECK(OTF2_GlobalDefWriter_WriteLocation(global, LOCATION, 1, OTF2_LOCATION_TYPE_CPU_THREAD, 2,
                                             0));
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
