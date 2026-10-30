#include "fs.h"
/* Shared workload: the native backend and RISC-V harness call these exact APIs.
 * Expected bytes/trees are derived separately in Python, not in this routine. */
long workload(unsigned operation)
{
    static unsigned char bytes[4096];
    for (unsigned i = 0; i < sizeof(bytes); i++) {
        bytes[i] = (i * 37U + 19U) & 255U;
    }
    if (operation == 14 || operation == 15) {
        static unsigned char publication[8192];
        for (unsigned index = 0; index < sizeof(publication); index++) {
            publication[index] = (index * 29U + 7U) & 255U;
        }
        return fs_store("publish", publication, sizeof(publication), operation == 15);
    }
    if (operation == 1) {
        return fs_open("split", FS_REPLACE);
    }
    if (operation == 5) {
        return fs_remove("alpha");
    }
    if (operation == 6) {
        return fs_defrag();
    }
    if (operation == 7) {
        return fs_open("alpha", FS_REPLACE);
    }
    long handle = fs_open("alpha", FS_RW);
    if (handle < 0) {
        return handle;
    }
    if (operation == 2) {
        long result = fs_seek(handle, 4900);
        if (result < 0) {
            return result;
        }
        return fs_write(handle, bytes, sizeof(bytes));
    }
    if (operation == 3) {
        return fs_append(handle, bytes, sizeof(bytes));
    }
    if (operation == 4) {
        return fs_truncate(handle, 20);
    }
    if (operation == 8) {
        return fs_truncate(handle, 65536);
    }
    return -4;
}
