#include "runtime.h"
#include "uart.h"

void finish(int status)
{
    volatile uint32_t *test = (volatile uint32_t *)0x100000UL;
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    *test = status == 0 ? 0x5555U : 0x13333U;
    for (;;) {
        __asm__ volatile("wfi");
    }
}

void fail(const char *message)
{
    uart_puts("FAIL: ");
    uart_puts(message);
    uart_puts("\n");
    finish(1);
}

void supervisor_fail(void)
{
    fail("unexpected S trap");
}

void machine_fail(void)
{
    fail("unexpected M trap");
}

void print_hex(uint64_t value)
{
    static const char digits[] = "0123456789abcdef";
    uart_puts("0x");
    for (int shift = 60; shift >= 0; shift -= 4) {
        uart_putc(digits[(value >> shift) & 15U]);
    }
}
