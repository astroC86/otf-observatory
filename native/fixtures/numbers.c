/* IEEE special values (±infinity, NaN) in double metrics and attributes, a UINT64_MAX metric,
 * and a creator string with quotes and a newline. */
#include "fixture.h"
#include <math.h>

enum { DOUBLE_METRIC = 0, INTEGER_METRIC = 1 }; /* metric class/instance and member ids */

static void write_events(OTF2_Archive *archive) {
    CHECK(OTF2_Archive_OpenEvtFiles(archive));
    OTF2_EvtWriter *writer = OTF2_Archive_GetEvtWriter(archive, 0);
    OTF2_AttributeList *attributes = OTF2_AttributeList_New();
    CHECK(OTF2_AttributeList_AddDouble(attributes, 0, INFINITY));
    CHECK(OTF2_EvtWriter_Enter(writer, attributes, 0, 0));
    OTF2_AttributeList_Delete(attributes);

    const OTF2_Type double_type = OTF2_TYPE_DOUBLE;
    const double samples[] = {INFINITY, -INFINITY, NAN, 3.5};
    for (unsigned i = 0; i < ARRAY_LENGTH(samples); i++) {
        OTF2_MetricValue value = {.floating_point = samples[i]};
        CHECK(OTF2_EvtWriter_Metric(writer, NULL, i + 1, DOUBLE_METRIC, 1, &double_type, &value));
    }
    const OTF2_Type integer_type = OTF2_TYPE_UINT64;
    OTF2_MetricValue integer = {.unsigned_int = UINT64_MAX};
    CHECK(OTF2_EvtWriter_Metric(writer, NULL, 4, INTEGER_METRIC, 1, &integer_type, &integer));
    CHECK(OTF2_EvtWriter_Leave(writer, NULL, 5, 0));
    CHECK(OTF2_Archive_CloseEvtWriter(archive, writer));
    CHECK(OTF2_Archive_CloseEvtFiles(archive));
}

static void write_metric(OTF2_GlobalDefWriter *global, OTF2_MetricRef id, OTF2_Type type) {
    CHECK(OTF2_GlobalDefWriter_WriteMetricMember(global, id, 2, 0, OTF2_METRIC_TYPE_OTHER,
                                                 OTF2_METRIC_ABSOLUTE_POINT, type,
                                                 OTF2_BASE_DECIMAL, 0, 0));
    const OTF2_MetricMemberRef member = id;
    CHECK(OTF2_GlobalDefWriter_WriteMetricClass(global, id, 1, &member, OTF2_METRIC_SYNCHRONOUS,
                                                OTF2_RECORDER_KIND_CPU));
}

static void write_global_definitions(OTF2_Archive *archive) {
    OTF2_GlobalDefWriter *global = OTF2_Archive_GetGlobalDefWriter(archive);
    CHECK(OTF2_GlobalDefWriter_WriteClockProperties(global, 1, 0, 6, OTF2_UNDEFINED_TIMESTAMP));
    static const char *const strings[] = {"", "Numbers", "magnitude"};
    write_strings(global, strings, ARRAY_LENGTH(strings));
    CHECK(OTF2_GlobalDefWriter_WriteRegion(global, 0, 1, 0, 0, OTF2_REGION_ROLE_FUNCTION,
                                           OTF2_PARADIGM_USER, OTF2_REGION_FLAG_NONE, 0, 0, 0));
    CHECK(OTF2_GlobalDefWriter_WriteAttribute(global, 0, 2, 0, OTF2_TYPE_DOUBLE));
    CHECK(
        OTF2_GlobalDefWriter_WriteSystemTreeNode(global, 0, 1, 0, OTF2_UNDEFINED_SYSTEM_TREE_NODE));
    CHECK(OTF2_GlobalDefWriter_WriteLocationGroup(global, 0, 1, OTF2_LOCATION_GROUP_TYPE_PROCESS, 0,
                                                  OTF2_UNDEFINED_LOCATION_GROUP));
    CHECK(OTF2_GlobalDefWriter_WriteLocation(global, 0, 1, OTF2_LOCATION_TYPE_CPU_THREAD, 7, 0));
    write_metric(global, DOUBLE_METRIC, OTF2_TYPE_DOUBLE);
    write_metric(global, INTEGER_METRIC, OTF2_TYPE_UINT64);
}

int main(int argc, char **argv) {
    if (argc != 2) {
        return 1;
    }
    OTF2_Archive *archive = open_archive(argv[1], "numbers");
    CHECK(OTF2_Archive_SetCreator(archive, "OTF2 viewer \"numeric\" fixture\n"));
    write_events(archive);
    write_global_definitions(archive);
    CHECK(OTF2_Archive_Close(archive));
    return 0;
}
