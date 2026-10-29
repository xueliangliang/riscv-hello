/* Test-only single-hart harness. The normal dual-hart kernel never reads this
 * control sector and links only journal's weak no-op hook. Software interruption
 * via QEMU finisher is NOT loss of a device's volatile write cache. */
#include "block.h"
#include "fs.h"
#include "journal.h"
#include "runtime.h"
#include "uart.h"
static unsigned char control[512];
static unsigned armed;
static unsigned at;
extern long workload(unsigned operation);
static unsigned get32(unsigned offset)
{
    return (unsigned)control[offset] | (unsigned)control[offset + 1] << 8 |
           (unsigned)control[offset + 2] << 16 | (unsigned)control[offset + 3] << 24;
}
void journal_hook(unsigned phase, unsigned index)
{
    if (phase == armed && (!at || index == at)) {
        uart_puts("INTERRUPT phase=");
        print_hex(phase);
        uart_puts(" index=");
        print_hex(index);
        uart_puts("\n");
        finish(0);
    }
}
int main(void)
{
    if (block_init() || block_request(0, 12000, control)) {
        fail("harness control READ");
    }
    unsigned operation = get32(0);
    unsigned phase = get32(4);
    at = get32(8);
    if (phase == 9) {
        armed = phase;
    }
    if (fs_mount()) {
        fail("harness mount rejected");
    }
    if (phase != 9) {
        armed = phase;
    }
    if (operation && workload(operation) < 0) {
        fail("harness mutator rejected");
    }
    if (phase) {
        fail("armed hook was not reached");
    }
    uart_puts("PASS harness clean return\n");
    return 0;
}
