/* otf2_reader: stream an OTF2 archive as JSON lines, one record per line, on stdout.
 *
 *   otf2_reader [--definitions-only] archive.otf2
 *
 * Output order: ArchiveProperties, all global definitions, ReaderProperties, each
 * location's local ClockOffset definitions, then (unless --definitions-only) all events
 * in global time order and the markers. Wire decoding, id mapping tables and clock
 * corrections are applied by libotf2 before the callbacks run. The per-record callbacks
 * in callbacks.inc are generated from the installed OTF2 headers by build_reader.py.
 *
 * Exit status: 0 on success, 1 on bad usage, 2 on an OTF2 or output error.
 */
#include <inttypes.h>
#include <math.h>
#include <otf2/otf2.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(call)                                                                                \
    do {                                                                                           \
        OTF2_ErrorCode check_error = (call);                                                       \
        if (check_error != OTF2_SUCCESS) {                                                         \
            fprintf(stderr, "%s: %s\n", #call, OTF2_Error_GetDescription(check_error));            \
            exit(2);                                                                               \
        }                                                                                          \
    } while (0)

static void fail(const char *message) {
    fprintf(stderr, "otf2_reader: %s\n", message);
    exit(2);
}

/* ------------------------------------------------------------------ JSON output */

static void json_string(const char *text) {
    putchar('"');
    for (const unsigned char *c = (const unsigned char *)(text ? text : ""); *c; c++) {
        if (*c == '"' || *c == '\\') {
            putchar('\\');
            putchar(*c);
        } else if (*c < 32) {
            printf("\\u%04x", *c);
        } else {
            putchar(*c);
        }
    }
    putchar('"');
}

/* JSON numbers cannot encode infinities or NaN, so those are written as the strings
 * "Infinity", "-Infinity" and "NaN"; the importer keeps their spelling for metrics. */
static void json_double(double value) {
    if (isfinite(value)) {
        printf("%.17g", value);
    } else {
        json_string(isnan(value) ? "NaN" : signbit(value) ? "-Infinity" : "Infinity");
    }
}

static void json_value(OTF2_Type type, OTF2_AttributeValue value) {
    switch (type) {
#define UNSIGNED(TYPE, FIELD)                                                                      \
    case OTF2_TYPE_##TYPE:                                                                         \
        printf("%" PRIu64, (uint64_t)value.FIELD);                                                 \
        break;
#define SIGNED(TYPE, FIELD)                                                                        \
    case OTF2_TYPE_##TYPE:                                                                         \
        printf("%" PRId64, (int64_t)value.FIELD);                                                  \
        break;
        UNSIGNED(UINT8, uint8)
        UNSIGNED(UINT16, uint16)
        UNSIGNED(UINT32, uint32)
        UNSIGNED(UINT64, uint64)
        SIGNED(INT8, int8)
        SIGNED(INT16, int16)
        SIGNED(INT32, int32)
        SIGNED(INT64, int64)
        /* Definition references are written as their numeric ids. */
        UNSIGNED(STRING, stringRef)
        UNSIGNED(ATTRIBUTE, attributeRef)
        UNSIGNED(LOCATION, locationRef)
        UNSIGNED(REGION, regionRef)
        UNSIGNED(GROUP, groupRef)
        UNSIGNED(METRIC, metricRef)
        UNSIGNED(COMM, commRef)
        UNSIGNED(PARAMETER, parameterRef)
        UNSIGNED(RMA_WIN, rmaWinRef)
        UNSIGNED(SOURCE_CODE_LOCATION, sourceCodeLocationRef)
        UNSIGNED(CALLING_CONTEXT, callingContextRef)
        UNSIGNED(INTERRUPT_GENERATOR, interruptGeneratorRef)
        UNSIGNED(IO_FILE, ioFileRef)
        UNSIGNED(IO_HANDLE, ioHandleRef)
        UNSIGNED(LOCATION_GROUP, locationGroupRef)
#undef UNSIGNED
#undef SIGNED
    case OTF2_TYPE_FLOAT:
        json_double(value.float32);
        break;
    case OTF2_TYPE_DOUBLE:
        json_double(value.float64);
        break;
    default:
        fputs("null", stdout);
    }
}

/* Append `,"attributes":[{"ref":…,"type":…,"value":…},…]` when the event has any. */
static void json_attributes(OTF2_AttributeList *attributes) {
    uint32_t count = attributes ? OTF2_AttributeList_GetNumberOfElements(attributes) : 0;
    if (!count) {
        return;
    }
    fputs(",\"attributes\":[", stdout);
    for (uint32_t i = 0; i < count; i++) {
        OTF2_AttributeRef ref;
        OTF2_Type type;
        OTF2_AttributeValue value;
        CHECK(OTF2_AttributeList_GetAttributeByIndex(attributes, i, &ref, &type, &value));
        if (i) {
            putchar(',');
        }
        printf("{\"ref\":%u,\"type\":%u,\"value\":", ref, type);
        json_value(type, value);
        putchar('}');
    }
    putchar(']');
}

/* ------------------------------------------------------------------ locations */

/* Locations seen in the global Location definitions, in definition order. The archive
 * header announces how many there are; more definitions than that is a corrupt archive. */
static uint64_t *locations;
static uint64_t location_count;
static uint64_t location_capacity;

static void add_location(OTF2_LocationRef location) {
    if (location_count == location_capacity) {
        fail("archive defines more locations than its header declares");
    }
    locations[location_count++] = location;
}

/* ------------------------------------------------------------------ callbacks */

/* Local clock offsets are the evidence for the correction libotf2 applies before the
 * global event callbacks run; they are reported in their original tick domain. */
static OTF2_CallbackCode clock_offset(void *user_data, OTF2_TimeStamp time, int64_t offset,
                                      double standard_deviation) {
    uint64_t location = *(const uint64_t *)user_data;
    printf("{\"record\":\"definition\",\"kind\":\"ClockOffset\",\"data\":{\"location\":%" PRIu64
           ",\"time\":%" PRIu64 ",\"offset\":%" PRId64 ",\"standardDeviation\":",
           location, time, offset);
    json_double(standard_deviation);
    fputs("}}\n", stdout);
    return OTF2_CALLBACK_SUCCESS;
}

#include "callbacks.inc" /* cb_* callbacks and register_GlobalDef/GlobalEvt/Marker */

/* ------------------------------------------------------------------ reading */

static void print_archive_properties(OTF2_Reader *reader, uint64_t location_total) {
    uint8_t major = 0, minor = 0, bugfix = 0;
    CHECK(OTF2_Reader_GetVersion(reader, &major, &minor, &bugfix));
    char *creator = NULL;
    CHECK(OTF2_Reader_GetCreator(reader, &creator));
    printf("{\"record\":\"definition\",\"kind\":\"ArchiveProperties\",\"data\":{\"major\":%u,"
           "\"minor\":%u,\"bugfix\":%u,\"numberOfLocations\":%" PRIu64 ",\"creator\":",
           major, minor, bugfix, location_total);
    json_string(creator);
    free(creator);
    fputs("}}\n", stdout);
}

static void read_global_definitions(OTF2_Reader *reader) {
    OTF2_GlobalDefReader *definitions = OTF2_Reader_GetGlobalDefReader(reader);
    if (!definitions) {
        fail("cannot open the global definitions");
    }
    OTF2_GlobalDefReaderCallbacks *callbacks = OTF2_GlobalDefReaderCallbacks_New();
    register_GlobalDef(callbacks);
    CHECK(OTF2_Reader_RegisterGlobalDefCallbacks(reader, definitions, callbacks, NULL));
    OTF2_GlobalDefReaderCallbacks_Delete(callbacks);
    uint64_t read = 0;
    CHECK(OTF2_Reader_ReadAllGlobalDefinitions(reader, definitions, &read));
    CHECK(OTF2_Reader_CloseGlobalDefReader(reader, definitions));
}

static void read_clock_offsets(OTF2_Reader *reader, uint64_t *location) {
    OTF2_DefReader *definitions = OTF2_Reader_GetDefReader(reader, *location);
    if (!definitions) {
        return; /* no local definition file for this location */
    }
    OTF2_DefReaderCallbacks *callbacks = OTF2_DefReaderCallbacks_New();
    CHECK(OTF2_DefReaderCallbacks_SetClockOffsetCallback(callbacks, clock_offset));
    CHECK(OTF2_Reader_RegisterDefCallbacks(reader, definitions, callbacks, location));
    OTF2_DefReaderCallbacks_Delete(callbacks);
    uint64_t read = 0;
    CHECK(OTF2_Reader_ReadAllLocalDefinitions(reader, definitions, &read));
    CHECK(OTF2_Reader_CloseDefReader(reader, definitions));
}

/* Read every location's clock offsets and, when events are wanted, open its event reader;
 * libotf2 needs both before the global event reader can merge and correct the streams. */
static void read_local_definitions(OTF2_Reader *reader, int with_events) {
    for (uint64_t i = 0; i < location_count; i++) {
        CHECK(OTF2_Reader_SelectLocation(reader, locations[i]));
    }
    int local_definitions = OTF2_Reader_OpenDefFiles(reader) == OTF2_SUCCESS;
    if (with_events) {
        CHECK(OTF2_Reader_OpenEvtFiles(reader));
    }
    printf("{\"record\":\"definition\",\"kind\":\"ReaderProperties\",\"data\":{"
           "\"clockOffsetsApplied\":true,\"localClockDefinitionsRetained\":%s}}\n",
           local_definitions ? "true" : "false");
    for (uint64_t i = 0; i < location_count; i++) {
        if (local_definitions) {
            read_clock_offsets(reader, &locations[i]);
        }
        if (with_events && !OTF2_Reader_GetEvtReader(reader, locations[i])) {
            fail("cannot open a location's event stream");
        }
    }
    if (local_definitions) {
        CHECK(OTF2_Reader_CloseDefFiles(reader));
    }
}

static void read_events(OTF2_Reader *reader) {
    OTF2_GlobalEvtReader *events = OTF2_Reader_GetGlobalEvtReader(reader);
    if (!events) {
        fail("cannot open the global event reader");
    }
    OTF2_GlobalEvtReaderCallbacks *callbacks = OTF2_GlobalEvtReaderCallbacks_New();
    register_GlobalEvt(callbacks);
    CHECK(OTF2_Reader_RegisterGlobalEvtCallbacks(reader, events, callbacks, NULL));
    OTF2_GlobalEvtReaderCallbacks_Delete(callbacks);
    uint64_t read = 0;
    CHECK(OTF2_Reader_ReadAllGlobalEvents(reader, events, &read));
    CHECK(OTF2_Reader_CloseGlobalEvtReader(reader, events));
    CHECK(OTF2_Reader_CloseEvtFiles(reader));
}

static void read_markers(OTF2_Reader *reader) {
    OTF2_MarkerReader *markers = OTF2_Reader_GetMarkerReader(reader);
    if (!markers) {
        return; /* archive without markers */
    }
    OTF2_MarkerReaderCallbacks *callbacks = OTF2_MarkerReaderCallbacks_New();
    register_Marker(callbacks);
    CHECK(OTF2_Reader_RegisterMarkerCallbacks(reader, markers, callbacks, NULL));
    OTF2_MarkerReaderCallbacks_Delete(callbacks);
    uint64_t read = 0;
    CHECK(OTF2_Reader_ReadAllMarkers(reader, markers, &read));
    CHECK(OTF2_Reader_CloseMarkerReader(reader, markers));
}

int main(int argc, char **argv) {
    int definitions_only = argc == 3 && strcmp(argv[1], "--definitions-only") == 0;
    if (argc != 2 && !definitions_only) {
        fprintf(stderr, "usage: otf2_reader [--definitions-only] archive.otf2\n");
        return 1;
    }
    setvbuf(stdout, NULL, _IOFBF, 1 << 20);
    OTF2_Reader *reader = OTF2_Reader_Open(argv[definitions_only ? 2 : 1]);
    if (!reader) {
        fail("cannot open the archive");
    }
    CHECK(OTF2_Reader_SetSerialCollectiveCallbacks(reader));

    uint64_t location_total = 0;
    CHECK(OTF2_Reader_GetNumberOfLocations(reader, &location_total));
    print_archive_properties(reader, location_total);
    location_capacity = location_total;
    locations = calloc(location_total ? location_total : 1, sizeof(uint64_t));
    if (!locations) {
        fail("out of memory");
    }

    read_global_definitions(reader);
    read_local_definitions(reader, !definitions_only);
    if (!definitions_only) {
        read_events(reader);
        read_markers(reader);
    }
    CHECK(OTF2_Reader_Close(reader));
    free(locations);
    return ferror(stdout) ? 2 : 0;
}
