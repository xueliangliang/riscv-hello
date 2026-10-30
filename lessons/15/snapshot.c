#include "snapshot.h"
#include "fs.h"
/* Only staging may be partially modified on failure, never the user target.
 * The scheduler/FS lock is held by the entire caller; no open handle escapes. */
long snapshot_read(const char *name, unsigned char *staging, unsigned capacity)
{
    if (!capacity || capacity > FS_BYTES) {
        return F_ARG;
    }
    long handle = fs_open(name, FS_EXISTING);
    if (handle < 0) {
        return handle;
    }
    unsigned done = 0;
    long result;
    for (;;) {
        unsigned remaining = capacity - done;
        if (!remaining) {
            unsigned char extra;
            result = fs_read(handle, &extra, 1);
            if (result > 0) {
                result = F_LIMIT;
            } else if (!result) {
                result = done;
            }
            break;
        }
        unsigned part = remaining > 4096 ? 4096 : remaining;
        result = fs_read(handle, staging + done, part);
        if (result < 0) {
            break;
        }
        if (!result) {
            result = done;
            break;
        }
        done += (unsigned)result;
    }
    long closed = fs_close(handle);
    if (closed < 0) {
        return closed;
    }
    return result;
}
