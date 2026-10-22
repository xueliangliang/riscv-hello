#include "runtime.h"
#include "uart.h"
#include "user-symbols.h"

#define TIMER_CAUSE ((1UL << 63) | 5UL)
#define TIMER_INTERVAL 100000UL
#define TIMER_COUNT 3U

static unsigned int started;
static unsigned int ticks;
static uint64_t deadline;
static uint64_t previous_progress;

static uint64_t read_time(void)
{
    uint64_t value;
    __asm__ volatile("rdtime %0" : "=r"(value));
    return value;
}

static void set_compare(uint64_t value)
{
    /* RV64 writes the whole Sstc CSR atomically. STIP follows time>=stimecmp;
       writing sip is NOT how this timer is acknowledged. */
    __asm__ volatile("csrw 0x14d, %0" :: "r"(value) : "memory");
}

static void arm_timer(void)
{
    deadline = read_time() + TIMER_INTERVAL;
    set_compare(deadline);
}

void supervisor_main(void)
{
    uart_puts("Lesson 06: direct Sstc timer, one user stream, no scheduler.\r\n");
    enter_user();
}

static void timer_interrupt(struct TrapFrame *frame)
{
    if (started == 0 || ticks >= TIMER_COUNT) {
        fail("timer phase");
    }
    if (frame->epc < U_INTERRUPT_LOOP || frame->epc >= U_INTERRUPT_LOOP_END ||
        ((frame->epc - U_INTERRUPT_LOOP) & 3UL) != 0) {
        fail("timer PC outside normal U loop");
    }
    if ((frame->status & 2UL) != 0 || frame->x[2] != USER_STACK_TOP) {
        fail("timer status or stack");
    }
    /* The privileged specification permits a delayed STIP deassertion.
       A spurious early delivery restores the same context without counting
       a tick. SIE is hardware-cleared; the handler never sets it. */
    if (read_time() < deadline) {
        return;
    }
    if (ticks != 0 && frame->x[8] <= previous_progress) {
        fail("user made no progress between interrupts");
    }
    previous_progress = frame->x[8];
    ticks++;
    if (ticks == TIMER_COUNT) {
        /* Mask delivery before publishing completion; park the comparator. */
        __asm__ volatile("csrc sie, %0" :: "r"(32UL) : "memory");
        set_compare(UINT64_MAX);
        *(volatile uint64_t *)U_USER_DONE = 1;
    } else {
        arm_timer();
    }
    uart_puts("timer: tick=");
    print_hex(ticks);
    uart_puts(" scause=");
    print_hex(frame->cause);
    uart_puts(" SPP=0 resume=");
    print_hex(frame->epc);
    uart_puts(" progress=");
    print_hex(frame->x[8]);
    uart_puts("\r\n");
    /* Exercise the epilogue's CSR restore instead of accidentally relying on
       hardware's entry sepc remaining untouched. Frame epc is NEVER +=4 here. */
    __asm__ volatile("csrw sepc, zero" ::: "memory");
}

void trap_dispatch(struct TrapFrame *frame)
{
    check_user_trap(frame);
    if (frame->cause == TIMER_CAUSE) {
        timer_interrupt(frame);
        return;
    }
    if (frame->cause != 8) {
        fail("unexpected scause");
    }
    if (frame->x[17] == 1 && frame->epc == U_START_ECALL && started == 0) {
        started = 1;
        uart_puts("user: before interrupts; entering normal instruction loop.\r\n");
        frame->epc += 4; /* Only this explicitly 32-bit synchronous ecall. */
        arm_timer();
        __asm__ volatile("csrs sie, %0" :: "r"(32UL) : "memory");
        return;
    }
    if (frame->x[17] == 2 && frame->epc == U_EXIT_ECALL && ticks == TIMER_COUNT) {
        if (frame->x[10] != 0) {
            fail("user register/stack self-check");
        }
        uart_puts("user: after interrupts; registers, SP, stack and progress verified.\r\n");
        uart_puts("PASS: three asynchronous timers returned to the same user stream.\r\n");
        finish(0);
    }
    fail("unexpected syscall or phase");
}
