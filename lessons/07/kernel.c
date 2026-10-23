#include "process.h"
#include "uart.h"
#include "user-symbols.h"
#define TIMER_CAUSE ((1UL << 63) | 5UL)
#define INTERVAL 100000UL
struct Process processes[TASK_SLOTS];
int current;
static unsigned long deadline;
static unsigned long timer_switches;

static unsigned long read_time(void)
{
    unsigned long value;
    __asm__ volatile("rdtime %0" : "=r"(value));
    return value;
}
static void arm_timer(void)
{
    deadline = read_time() + INTERVAL;
    __asm__ volatile("csrw 0x14d, %0" :: "r"(deadline) : "memory");
}
static void clear_bytes(unsigned long begin, unsigned long end)
{
    for (unsigned long address = begin; address < end; address++) {
        *(unsigned char *)address = 0;
    }
}
static void event(const char *name, long pid, long value)
{
    uart_puts(name);
    uart_puts(" pid=");
    print_hex(pid);
    uart_puts(" value=");
    print_hex(value);
    uart_puts("\r\n");
}
static struct Process *lookup(long pid)
{
    if (pid <= 0) {
        return 0;
    }
    unsigned long slot = (unsigned long)pid & 15UL;
    if (slot >= TASK_SLOTS) {
        return 0;
    }
    struct Process *process = &processes[slot];
    if (process->state == FREE || process->pid != pid) {
        return 0;
    }
    return process;
}
static long owned(long pid, struct Process **child)
{
    *child = lookup(pid);
    if (*child == 0) {
        return E_PID;
    }
    if ((*child)->parent != processes[current].pid) {
        return E_OWNER;
    }
    return 0;
}
static long launch(int slot, int entry, long argument)
{
    struct Process *process = &processes[slot];
    unsigned long generation = process->generation + 1;
    /* Never wrap a generation back into a stale PID. */
    if (generation > 0x07ffffffffffffffUL) {
        return E_FULL;
    }
    clear_bytes((unsigned long)process, (unsigned long)(process + 1));
    process->generation = generation;
    process->pid = (long)(generation * 16 + slot);
    process->parent = slot == 0 ? 0 : processes[current].pid;
    process->state = READY;
    process->entry = entry;
    unsigned long bottom = STACK_BASE + slot * STACK_SIZE;
    clear_bytes(bottom, bottom + STACK_SIZE);
    process->frame.x[2] = bottom + STACK_SIZE;
    process->frame.x[10] = entry;
    process->frame.x[11] = argument;
    unsigned long data_address = DATA_BASE + slot * DATA_SIZE;
    clear_bytes(data_address, data_address + DATA_SIZE);
    struct UserData *data = (struct UserData *)data_address;
    data->canary = process->pid;
    process->frame.x[12] = data_address;
    process->frame.epc = slot == 0 ? U_USER_ENTRY : U_WORKER_MAIN;
    if (entry == WORK_SPIN) {
        process->frame.epc = U_SPIN_WORKER;
    }
    /* UXL=64, SPP=0, SPIE=1; sret enables interrupts only in U mode. */
    process->frame.status = 0x200000020UL;
    event("spawn", process->pid, entry);
    return process->pid;
}
static void reap(struct Process *child)
{
    event("reap", child->pid, child->status);
    /* Keep generation, but not PID validity. No allocation before this step. */
    child->state = FREE;
}
static void terminate(struct Process *child, long status)
{
    child->status = status;
    child->state = ZOMBIE;
    event("zombie", child->pid, status);
    struct Process *parent = lookup(child->parent);
    if (parent != 0 && parent->state == WAITING &&
        parent->waiting_for == child->pid) {
        parent->frame.x[10] = status;
        parent->state = READY;
        event("wait-return", parent->pid, status);
        reap(child);
    }
}
static void wake_sleepers(void)
{
    unsigned long now = read_time();
    for (int i = 0; i < TASK_SLOTS; i++) {
        if (processes[i].state == SLEEPING && now >= processes[i].wake_at) {
            processes[i].state = READY;
            event("wake", processes[i].pid, 0);
        }
    }
}
/* The returned pointer is consumed by trap.S. A process owns its saved frame;
   the next trap may overwrite the temporary frame on the hart kernel stack. */
static struct TrapFrame *schedule(int timer)
{
    int previous = current;
    if (processes[current].state == RUNNING) {
        processes[current].state = READY;
    }
    for (;;) {
        wake_sleepers();
        for (int offset = 1; offset <= TASK_SLOTS; offset++) {
            int slot = (previous + offset) % TASK_SLOTS;
            if (processes[slot].state == READY) {
                current = slot;
                processes[slot].state = RUNNING;
                if (timer && current != previous) {
                    timer_switches++;
                    event("timer-switch", processes[previous].pid, processes[current].pid);
                }
                arm_timer();
                return &processes[slot].frame;
            }
        }
        /* No U context can run. SIE stays clear; bounded time polling wakes
           sleepers without saving a fake U frame. This is NOT an idle task.
           Lesson08 must replace this with a per-hart lock-aware idle path. */
        int sleeping = 0;
        for (int i = 0; i < TASK_SLOTS; i++) {
            if (processes[i].state == SLEEPING) {
                sleeping = 1;
            }
        }
        if (!sleeping) {
            fail("scheduler deadlock");
        }
    }
}
static int readable(unsigned long pointer, unsigned long length)
{
    /* No user pointer is used by lifecycle calls. WRITE alone accepts bytes
       in shared image/data or the CALLER's own stack, using subtraction to
       avoid pointer+length overflow. This is validation, not isolation. */
    unsigned long low = STACK_BASE + current * STACK_SIZE;
    unsigned long high = low + STACK_SIZE;
    if (pointer >= USER_BASE && pointer < USER_DATA_END &&
        length <= USER_DATA_END - pointer) {
        return 1;
    }
    unsigned long data_low = DATA_BASE + current * DATA_SIZE;
    if (pointer >= data_low && pointer < data_low + DATA_SIZE &&
        length <= data_low + DATA_SIZE - pointer) {
        return 1;
    }
    return pointer >= low && pointer < high && length <= high - pointer;
}
static long syscall(struct Process *process, int *reschedule)
{
    long number = process->frame.x[17];
    long first = process->frame.x[10];
    unsigned long second = process->frame.x[11];
    struct Process *child;
    long error;
    switch (number) {
    case SYS_WRITE:
        if (second > 256 || !readable((unsigned long)first, second)) {
            return E_ARG;
        }
        for (unsigned long i = 0; i < second; i++) {
            uart_putc(((const char *)first)[i]);
        }
        return second;
    case SYS_SPAWN:
        /* Controller-only spawning keeps this chapter's parent/orphan policy
           explicit: workers cannot create descendants; controller cannot exit. */
        if (current != 0) {
            return E_OWNER;
        }
        if (first < WORK_SPIN || first > WORK_OWNER) {
            return E_ARG;
        }
        for (int i = 1; i < TASK_SLOTS; i++) {
            if (processes[i].state == FREE) {
                return launch(i, first, second);
            }
        }
        return E_FULL;
    case SYS_SLEEP:
        if (first <= 0 || first > 1000) {
            return E_ARG;
        }
        process->wake_at = read_time() + (unsigned long)first * INTERVAL;
        process->state = SLEEPING;
        event("sleep", process->pid, first);
        *reschedule = 1;
        return 0;
    case SYS_EXIT:
        if (current == 0 || first < 0 || first > 255) {
            return E_ARG;
        }
        terminate(process, first);
        *reschedule = 1;
        return 0;
    case SYS_WAIT:
    case SYS_KILL:
    case SYS_STATE:
    case SYS_HITS:
        error = owned(first, &child);
        if (error != 0) {
            return error;
        }
        if (number == SYS_STATE) {
            return child->state;
        }
        if (number == SYS_HITS) {
            return child->timer_hits;
        }
        if (number == SYS_KILL) {
            if (child->state == ZOMBIE) {
                return E_ARG;
            }
            event("kill", child->pid, child->state);
            terminate(child, 137);
            return 0;
        }
        /* Valid WAIT only: record the target before either completion path. */
        event("wait-call", process->pid, child->pid);
        if (child->state == ZOMBIE) {
            long status = child->status;
            reap(child);
            event("wait-return", process->pid, status);
            return status;
        }
        process->state = WAITING;
        process->waiting_for = child->pid;
        event("wait-block", process->pid, child->pid);
        *reschedule = 1;
        return 0;
    case SYS_DONE:
        if (current != 0 || timer_switches < 2) {
            fail("completion ownership or timer evidence");
        }
        for (int i = 1; i < TASK_SLOTS; i++) {
            if (processes[i].state != FREE) {
                fail("completion leaked child");
            }
        }
        uart_puts("PASS: lesson07 preemptive scheduler and lifecycle.\r\n");
        finish(0);
    case SYS_FAIL:
        fail("user assertion");
    default:
        return E_ARG;
    }
}
struct TrapFrame *trap_dispatch(struct TrapFrame *frame)
{
    struct Process *process = &processes[current];
    unsigned long low = STACK_BASE + current * STACK_SIZE;
    if ((frame->status & 256UL) != 0 || frame->x[2] < low ||
        frame->x[2] > low + STACK_SIZE || (frame->x[2] & 15UL) != 0) {
        fail("trap privilege or stack");
    }
    process->frame = *frame;
    if (frame->cause == TIMER_CAUSE) {
        /* STIP deassertion may lag the stimecmp write: ignore early delivery. */
        if (read_time() < deadline) {
            return &process->frame;
        }
        process->timer_hits++;
        if (process->entry == WORK_SPIN && frame->epc >= U_SPIN_LOOP &&
            frame->epc < U_SPIN_LOOP_END) {
            struct UserData *data = (struct UserData *)(DATA_BASE + current * DATA_SIZE);
            if (frame->x[12] != (unsigned long)data || data->canary != (unsigned long)process->pid ||
                data->counter > frame->x[8] || data->counter + 1 < frame->x[8] ||
                frame->x[13] != 0x12345 || frame->x[18] != 0x54321 ||
                *(unsigned long *)(low + STACK_SIZE - 8) != 0x13579 ||
                frame->x[8] <= process->previous_progress) {
                fail("spin context restore");
            }
            process->previous_progress = frame->x[8];
            uart_puts("preempt-loop pc=");
            print_hex(frame->epc);
            event("", process->pid, frame->x[8]);
        }
        /* Never increment an asynchronous resume PC. */
        return schedule(1);
    }
    if (frame->cause != 8) {
        fail("unexpected user trap");
    }
    process->frame.epc += 4;
    int reschedule = 0;
    long result = syscall(process, &reschedule);
    process->frame.x[10] = result;
    if (reschedule) {
        return schedule(0);
    }
    return &process->frame;
}
void supervisor_main(void)
{
    uart_puts("Lesson 07: single-hart preemptive processes, flat memory.\r\n");
    clear_bytes(U___USER_BSS_START, U___USER_BSS_END);
    __asm__ volatile("fence.i" ::: "memory");
    extern void supervisor_trap(void);
    __asm__ volatile("csrw stvec, %0" :: "r"(supervisor_trap));
    __asm__ volatile("csrw sie, %0" :: "r"(32UL));
    launch(0, 0, 0);
    current = 0;
    processes[0].state = RUNNING;
    arm_timer();
    restore_frame(&processes[0].frame);
}
