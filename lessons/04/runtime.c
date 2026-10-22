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
    uart_puts("\r\n");
    finish(1);
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

void report_trap(const struct TrapFrame *frame)
{
    uart_puts("trap: scause=");
    print_hex(frame->cause);
    uart_puts(" sepc=");
    print_hex(frame->epc);
    uart_puts((frame->status & 256U) == 0 ? " SPP=0\r\n" : " SPP=1\r\n");
}

void check_user_trap(const struct TrapFrame *frame)
{
    if ((frame->status & 256U) != 0) {
        fail("trap did not originate in U");
    }
    if (frame->x[2] < USER_STACK_BOTTOM || frame->x[2] > USER_STACK_TOP ||
        (frame->x[2] & 15U) != 0) {
        fail("invalid user stack");
    }
}
