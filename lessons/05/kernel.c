#include "runtime.h"
#include "uart.h"
#include "abi.h"

static int first_trap = 1;

void supervisor_main(void)
{
    uart_puts("Lesson 05: supervisor ready for syscall ABI.\r\n");
    enter_user();
}

static long console_write(uint64_t pointer, uint64_t length)
{
    /* Length first, then subtraction-based bounds: never form pointer+length. */
    if (length > WRITE_MAX) {
        return ERR_INVALID;
    }
    if (pointer < USER_BASE || pointer > USER_END ||
        length > USER_END - pointer) {
        return ERR_FAULT;
    }
    const char *text = (const char *)(uintptr_t)pointer;
    for (uint64_t index = 0; index < length; index++) {
        uart_putc(text[index]);
    }
    return (long)length;
}

void trap_dispatch(struct TrapFrame *frame)
{
    if (first_trap != 0) {
        report_trap(frame);
        first_trap = 0;
    }
    check_user_trap(frame);
    if (frame->cause != 8) {
        fail("unexpected scause");
    }
    if (frame->epc != 0x8040001cUL) {
        fail("unexpected sepc");
    }
    long result;
    switch (frame->x[17]) {
    case SYS_WRITE:
        result = console_write(frame->x[10], frame->x[11]);
        break;
    case SYS_EXIT:
        if (frame->x[10] != 0) {
            fail("user exit status");
        }
        uart_puts("PASS: user exit(0) recovered to supervisor.\r\n");
        finish(0);
    default:
        result = ERR_NOSYS;
        break;
    }
    frame->x[10] = (uint64_t)result;
    frame->epc += 4;
}
