/* Host thread plus two accelerator streams with separate clock offset samples, so the
 * importer's per-location host/device clock correction can be checked. */
#include "fixture.h"

enum { HOST, STREAM, SECOND_STREAM };
enum { LAUNCH, KERNEL }; /* region ids */

static void write_events(OTF2_Archive *archive) {
    CHECK(OTF2_Archive_OpenEvtFiles(archive));
    OTF2_EvtWriter *writer = OTF2_Archive_GetEvtWriter(archive, HOST);
    CHECK(OTF2_EvtWriter_Enter(writer, NULL, 130, LAUNCH));
    CHECK(OTF2_EvtWriter_Leave(writer, NULL, 140, LAUNCH));
    CHECK(OTF2_Archive_CloseEvtWriter(archive, writer));

    writer = OTF2_Archive_GetEvtWriter(archive, STREAM);
    CHECK(OTF2_EvtWriter_Enter(writer, NULL, 95, KERNEL));
    CHECK(OTF2_EvtWriter_Leave(writer, NULL, 105, KERNEL));
    CHECK(OTF2_EvtWriter_Enter(writer, NULL, 115, KERNEL));
    CHECK(OTF2_EvtWriter_Leave(writer, NULL, 205, KERNEL));
    CHECK(OTF2_Archive_CloseEvtWriter(archive, writer));

    writer = OTF2_Archive_GetEvtWriter(archive, SECOND_STREAM);
    CHECK(OTF2_EvtWriter_Enter(writer, NULL, 10, KERNEL));
    CHECK(OTF2_EvtWriter_Leave(writer, NULL, 20, KERNEL));
    CHECK(OTF2_Archive_CloseEvtWriter(archive, writer));
    CHECK(OTF2_Archive_CloseEvtFiles(archive));
}

static void write_local_definitions(OTF2_Archive *archive) {
    CHECK(OTF2_Archive_OpenDefFiles(archive));
    OTF2_DefWriter *writer = OTF2_Archive_GetDefWriter(archive, HOST);
    CHECK(OTF2_DefWriter_WriteClockOffset(writer, 0, 0, .25));
    CHECK(OTF2_DefWriter_WriteClockOffset(writer, 1000, 0, .5));
    CHECK(OTF2_Archive_CloseDefWriter(archive, writer));

    writer = OTF2_Archive_GetDefWriter(archive, STREAM);
    CHECK(OTF2_DefWriter_WriteClockOffset(writer, 100, 100, 1.25));
    CHECK(OTF2_DefWriter_WriteClockOffset(writer, 200, 110, 2.5));
    CHECK(OTF2_Archive_CloseDefWriter(archive, writer));

    writer = OTF2_Archive_GetDefWriter(archive, SECOND_STREAM);
    CHECK(OTF2_DefWriter_WriteClockOffset(writer, 0, 1000, 3.5));
    CHECK(OTF2_Archive_CloseDefWriter(archive, writer));
    CHECK(OTF2_Archive_CloseDefFiles(archive));
}

static void write_global_definitions(OTF2_Archive *archive) {
    OTF2_GlobalDefWriter *global = OTF2_Archive_GetGlobalDefWriter(archive);
    CHECK(OTF2_GlobalDefWriter_WriteClockProperties(global, 100, 0, 400, OTF2_UNDEFINED_TIMESTAMP));
    static const char *const strings[] = {"", "host", "CUDA stream", "cudaLaunchKernel", "kernel"};
    write_strings(global, strings, ARRAY_LENGTH(strings));
    CHECK(
        OTF2_GlobalDefWriter_WriteSystemTreeNode(global, 0, 1, 0, OTF2_UNDEFINED_SYSTEM_TREE_NODE));
    CHECK(OTF2_GlobalDefWriter_WriteLocationGroup(global, 0, 1, OTF2_LOCATION_GROUP_TYPE_PROCESS, 0,
                                                  OTF2_UNDEFINED_LOCATION_GROUP));
    CHECK(OTF2_GlobalDefWriter_WriteLocation(global, HOST, 1, OTF2_LOCATION_TYPE_CPU_THREAD, 2, 0));
    CHECK(OTF2_GlobalDefWriter_WriteLocation(global, STREAM, 2,
                                             OTF2_LOCATION_TYPE_ACCELERATOR_STREAM, 4, 0));
    CHECK(OTF2_GlobalDefWriter_WriteLocation(global, SECOND_STREAM, 2,
                                             OTF2_LOCATION_TYPE_ACCELERATOR_STREAM, 2, 0));
    CHECK(OTF2_GlobalDefWriter_WriteRegion(global, LAUNCH, 3, 0, 0, OTF2_REGION_ROLE_FUNCTION,
                                           OTF2_PARADIGM_CUDA, OTF2_REGION_FLAG_NONE, 0, 0, 0));
    CHECK(OTF2_GlobalDefWriter_WriteRegion(global, KERNEL, 4, 0, 0, OTF2_REGION_ROLE_KERNEL,
                                           OTF2_PARADIGM_CUDA, OTF2_REGION_FLAG_NONE, 0, 0, 0));
}

int main(int argc, char **argv) {
    if (argc != 2) {
        return 1;
    }
    OTF2_Archive *archive = open_archive(argv[1], "clocks");
    write_events(archive);
    write_local_definitions(archive);
    write_global_definitions(archive);
    CHECK(OTF2_Archive_Close(archive));
    return 0;
}
