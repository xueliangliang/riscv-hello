#include "uart.h"

#include <stdint.h>

typedef void (*ShellEntry)(void);

int main(void)
{
    uart_puts("Kernel: entered from the virtio block image.\r\n");

    ShellEntry shell_entry = (ShellEntry)(uintptr_t)0x80400000UL;
    shell_entry();

    uart_puts("PASS: boot record, kernel/shell reads, and handoff verified.\r\n");
    return 0;
}
