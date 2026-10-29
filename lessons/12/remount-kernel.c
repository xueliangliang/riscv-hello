/* Test-only, same-runtime recovery through the real MMIO block driver. */
#include "block.h"
#include "fs.h"
#include "journal.h"
#include "runtime.h"
#include "uart.h"
extern long workload(unsigned operation);

int main(void)
{
    if (fs_mount()) {
        fail("initial remount-test mount");
    }
    if (workload(2) != F_IO) {
        fail("once-only WRITE did not return F_IO");
    }
    unsigned long requests = block_reads + block_writes + block_flushes;
    journal_abort();
    if (journal_error() != J_IO || fs_sync() != F_IO || fs_defrag() != F_IO ||
        block_request(4, 0, 0) == 0 ||
        requests != block_reads + block_writes + block_flushes) {
        fail("IO poison escaped before reset");
    }
    uart_puts("PASS sticky IO poison before reset\n");
    if (fs_mount()) {
        fail("same-runtime remount after once-only IOERR");
    }
    if (fs_sync() || block_reads + block_writes + block_flushes <= requests) {
        fail("remount did not resume real device requests");
    }
    long handle = fs_open("resumed", FS_REPLACE);
    if (handle < 4 || fs_write(handle, "after-reset", 11) != 11 ||
        fs_close(handle) || fs_sync()) {
        fail("mutation after remount");
    }
    uart_puts("PASS real-driver same-runtime remount and mutation\n");
    return 0;
}
