/* Shared helpers for the test trace writers in this directory.
 *
 * Each fixture is a standalone program: `fixture <archive-dir> [args]` writes a small
 * OTF2 archive through the installed public writer API and exits non-zero on error.
 */
#ifndef OTF2_VIEWER_FIXTURE_H
#define OTF2_VIEWER_FIXTURE_H

#include <otf2/otf2.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define ARRAY_LENGTH(array) (sizeof(array) / sizeof((array)[0]))

/* Abort with the OTF2 error description when a writer call fails. */
#define CHECK(call)                                                                                \
    do {                                                                                           \
        OTF2_ErrorCode check_error = (call);                                                       \
        if (check_error != OTF2_SUCCESS) {                                                         \
            fprintf(stderr, "%s: %s\n", #call, OTF2_Error_GetDescription(check_error));            \
            exit(2);                                                                               \
        }                                                                                          \
    } while (0)

static inline OTF2_FlushType flush_always(void *user_data, OTF2_FileType file_type,
                                          OTF2_LocationRef location, void *callee_data,
                                          bool final) {
    (void)user_data, (void)file_type, (void)location, (void)callee_data, (void) final;
    return OTF2_FLUSH;
}

/* Open `<directory>/<name>.otf2` for writing with serial (non-MPI) collectives. */
static inline OTF2_Archive *open_archive(const char *directory, const char *name) {
    OTF2_Archive *archive =
        OTF2_Archive_Open(directory, name, OTF2_FILEMODE_WRITE, 1024 * 1024, 1024 * 1024,
                          OTF2_SUBSTRATE_POSIX, OTF2_COMPRESSION_NONE);
    if (!archive) {
        exit(2);
    }
    static const OTF2_FlushCallbacks flush = {.otf2_pre_flush = flush_always,
                                              .otf2_post_flush = NULL};
    CHECK(OTF2_Archive_SetFlushCallbacks(archive, &flush, NULL));
    CHECK(OTF2_Archive_SetSerialCollectiveCallbacks(archive));
    return archive;
}

/* Write strings 0..count-1 with the given texts. */
static inline void write_strings(OTF2_GlobalDefWriter *global, const char *const *texts,
                                 size_t count) {
    for (size_t i = 0; i < count; i++) {
        CHECK(OTF2_GlobalDefWriter_WriteString(global, (OTF2_StringRef)i, texts[i]));
    }
}

/* Write empty local definition files for locations that need no mappings or clock offsets. */
static inline void write_empty_local_definitions(OTF2_Archive *archive,
                                                 const OTF2_LocationRef *locations, size_t count) {
    CHECK(OTF2_Archive_OpenDefFiles(archive));
    for (size_t i = 0; i < count; i++) {
        OTF2_DefWriter *writer = OTF2_Archive_GetDefWriter(archive, locations[i]);
        CHECK(OTF2_Archive_CloseDefWriter(archive, writer));
    }
    CHECK(OTF2_Archive_CloseDefFiles(archive));
}

#endif
