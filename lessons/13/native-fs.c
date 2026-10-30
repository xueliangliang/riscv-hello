/* Native-only observation of the REAL FS handle table; never linked in guest. */
#include "fs.c"
unsigned test_live_handles(void)
{
    unsigned count = 0;
    for (unsigned i = 0; i < FS_HANDLES; i++) {
        count += handles[i].live != 0;
    }
    return count;
}
