#include "uart.h"

__attribute__((section(".text.init")))
void shell_entry(void)
{
    uart_puts("Shell payload: loaded from disk and called by the kernel.\r\n");
}
