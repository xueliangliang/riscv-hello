#include "uart.h"

#include <stdint.h>

volatile uint32_t bss_probe;
volatile uint32_t initialized_data_probe = 0x4c4c3032U;

extern uint8_t __stack_bottom[];
extern uint8_t __stack_top[];

static int fail(const char *message)
{
    uart_puts("FAIL: ");
    uart_puts(message);
    uart_puts("\r\n");
    return 1;
}

int main(void)
{
    uint32_t local_probe = 0x5354414bU;
    uintptr_t stack_pointer;

    __asm__ volatile("mv %0, sp" : "=r"(stack_pointer));

    if (bss_probe != 0U) {
        return fail("BSS was not cleared before main.");
    }

    if (initialized_data_probe != 0x4c4c3032U) {
        return fail("initialized data was not loaded.");
    }

    if (local_probe != 0x5354414bU) {
        return fail("stack local did not retain its value.");
    }

    if (stack_pointer < (uintptr_t)__stack_bottom ||
        stack_pointer > (uintptr_t)__stack_top) {
        return fail("stack pointer is outside the linker stack range.");
    }

    uart_puts("Lesson 02: C main entered with a valid stack.\r\n");
    uart_puts("PASS: BSS was cleared and initialized data was preserved.\r\n");
    return 0;
}
