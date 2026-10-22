#include "runtime.h"
#include "uart.h"

static unsigned int phase;

void supervisor_main(void)
{
    uart_puts("Lesson 04: supervisor entered after mret.\r\n");
    enter_user();
}

void trap_dispatch(struct TrapFrame *frame)
{
    static const uint64_t causes[] = {8, 2, 8};
    static const uint64_t pcs[] = {0x80400010UL, 0x80400020UL, 0x80400030UL};
    report_trap(frame);
    check_user_trap(frame);
    if (phase >= 3 || frame->cause != causes[phase]) {
        fail("unexpected scause");
    }
    if (frame->epc != pcs[phase]) {
        fail("unexpected sepc");
    }
    if (phase == 0) {
        if (frame->x[17] != 0 || frame->x[5] != 0x123 ||
            frame->x[6] != 0x456 || frame->x[9] != 0x789 ||
            frame->x[13] != 0xabc) {
            fail("register context");
        }
        frame->x[10] = 42;
    }
    if (phase == 2) {
        if (frame->x[17] != 1 || frame->x[10] != 0) {
            fail("user register self-test");
        }
        uart_puts("PASS: M -> S -> U, ecall, CSR fault, context, S recovery.\r\n");
        finish(0);
    }
    /* Both probes are explicitly uncompressed 32-bit instructions. */
    frame->epc += 4;
    phase++;
}
