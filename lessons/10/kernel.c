#include "process.h"
#include "fs.h"
#include "uart.h"
#include "user-symbols.h"
#define TIMER_CAUSE ((1UL << 63) | 5UL)
#define INTERVAL 100000UL
struct Process processes[TASK_SLOTS];
struct Hart harts[2];
static unsigned int scheduler_lock;
static int scheduler_owner;
static unsigned long remote_kills;
static struct TrapFrame idle_frames[2];
static unsigned long idle_stacks[2][32] __attribute__((aligned(16)));
#define EXTERNAL_CAUSE ((1UL << 63) | 9UL)
#define RX_CAPACITY 128
static unsigned char rx_ring[RX_CAPACITY];
static unsigned long rx_head, rx_tail, rx_count;
static unsigned long rx_dropped, rx_received, external_irqs, read_blocks, read_wakes;
static unsigned long rx_consumed, head_wraps, tail_wraps;
static volatile unsigned char *const serial = (void *)0x10000000UL;
static volatile unsigned int *const claim = (void *)0x0c201004UL;

/* The only UART receive-register access lives in this claimed IRQ handler.
   All enqueue, empty-check and waiter publication use scheduler_lock. */
void console_interrupt(void)
{
    unsigned int source = *claim;
    if (source == 0) {
        return;
    }
    if (source != 10 || this_hart()->id != 0) {
        fail("unexpected PLIC source/context");
    }
    external_irqs++;
    while (serial[5] & 1) {
        unsigned char byte = serial[0];
        rx_received++;
        if (rx_count == RX_CAPACITY) {
            rx_dropped++; /* Drop NEWEST; never overwrite unread input. */
        } else {
            rx_ring[rx_head] = byte;
            rx_head = (rx_head + 1) % RX_CAPACITY;
            head_wraps += rx_head == 0;
            rx_count++;
        }
    }
    if (processes[0].state == READING && rx_count != 0) {
        processes[0].frame.x[10] = rx_ring[rx_tail];
        rx_tail = (rx_tail + 1) % RX_CAPACITY;
        tail_wraps += rx_tail == 0;
        rx_consumed++;
        rx_count--;
        processes[0].state = READY;
        read_wakes++;
    }
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    *claim = source;
}

/* SIE is already clear in S: an owner cannot be preempted while holding this
   lock. Acquire/release order the process table AND complete saved frames. */
static void lock_scheduler(void)
{
    unsigned long status;
    __asm__ volatile("csrr %0, sstatus" : "=r"(status));
    if (status & 2UL) {
        fail("SIE enabled before scheduler lock");
    }
    while (__atomic_exchange_n(&scheduler_lock, 1, __ATOMIC_ACQUIRE)) {
        __asm__ volatile("nop");
    }
    scheduler_owner = this_hart()->id;
}
static void unlock_scheduler(void)
{
    if (scheduler_owner != this_hart()->id) {
        fail("scheduler lock ownership");
    }
    scheduler_owner = -1;
    __atomic_store_n(&scheduler_lock, 0, __ATOMIC_RELEASE);
}

static unsigned long read_time(void)
{
    unsigned long value;
    __asm__ volatile("rdtime %0" : "=r"(value));
    return value;
}
static void arm_timer(void)
{
    this_hart()->deadline = read_time() + INTERVAL;
    __asm__ volatile("csrw 0x14d, %0" :: "r"(this_hart()->deadline) : "memory");
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
    uart_puts("\n");
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
    process->affinity = slot & 1;
    process->owner = -1;
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
    /* Publish READY only after stack, data and all 288 context bytes exist. */
    process->state = READY;
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
    child->owner = -1;
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
    struct Hart *hart = this_hart();
    int previous = current;
    if (previous >= 0) {
        struct Process *process = &processes[previous];
        if (process->state == RUNNING) {
            process->state = READY;
        }
        process->owner = -1;
    }
    current = -1;
    for (;;) {
        wake_sleepers();
        for (int offset = 1; offset <= TASK_SLOTS; offset++) {
            int slot = (previous + offset + TASK_SLOTS) % TASK_SLOTS;
            struct Process *process = &processes[slot];
            if (process->state != READY || process->affinity != hart->id) {
                continue;
            }
            if (process->owner != -1) {
                fail("READY process still owned");
            }
            current = slot;
            process->state = RUNNING;
            process->owner = hart->id;
            if (timer && previous >= 0 && current != previous) {
                hart->timer_switches++;
                event("timer-switch", processes[previous].pid, process->pid);
            }
            arm_timer();
            /* Reservation remains RUNNING/owner after unlocking. No other hart
               may select, reap, or overwrite it while assembly restores it. */
            unlock_scheduler();
            return &process->frame;
        }
        /* Genuine U-mode idle: trap entry uses this hart's trusted S stack.
           Interrupts are enabled by sret, never in S or while lock is held.
           A timer closes READY publication races without a bespoke IPI. */
        hart->idle_passes++;
        arm_timer();
        unlock_scheduler();
        return &idle_frames[hart->id];
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
static long file_syscall(long number, unsigned long first, unsigned long second,
                         unsigned long third)
{
    /* Explicit shell-only ABI: no file handles can leak through worker exit. */
    if (current != 0) {
        return E_OWNER;
    }
    if (number == FS_OPEN || number == FS_REMOVE) {
        char name[32];
        unsigned i;
        for (i = 0; i < sizeof(name); i++) {
            if (!readable(first + i, 1) || first + i < first) {
                return E_ARG;
            }
            name[i] = *(const char *)(first + i);
            if (!name[i]) {
                break;
            }
        }
        if (i == sizeof(name) || second > 1) {
            return E_ARG;
        }
        return number == FS_OPEN ? fs_open(name, second) : fs_remove(name);
    }
    if (number == FS_READ || number == FS_WRITE) {
        if (third > 4096 || !readable(second, third)) {
            return E_ARG;
        }
        return number == FS_READ ? fs_read(first, (void *)second, third) :
               fs_write(first, (const void *)second, third);
    }
    if (number == FS_FLUSH) {
        return fs_flush(first);
    }
    if (number == FS_CLOSE) {
        return fs_close(first);
    }
    if (number == FS_LIST) {
        return fs_list();
    }
    if (number == FS_INFO) {
        fs_info();
        return 0;
    }
    return E_ARG;
}
static long syscall(struct Process *process, int *reschedule)
{
    long number = process->frame.x[17];
    long first = process->frame.x[10];
    unsigned long second = process->frame.x[11];
    struct Process *child;
    long error;
    if (number >= FS_OPEN && number <= FS_INFO) {
        return file_syscall(number, first, second, process->frame.x[12]);
    }
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
        if (first < WORK_SPIN || first > WORK_EXIT) {
            return E_ARG;
        }
        if ((first == WORK_SLEEP && (second < 1 || second > 1000)) ||
            (first != WORK_SLEEP && second > 255)) {
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
            if (child->state == RUNNING) {
                /* Never recycle a remotely executing frame/stack. Its owner
                   acknowledges at its next trap (bounded by timer interval). */
                if (child->owner < 0 || child->owner == this_hart()->id) {
                    fail("invalid remote owner");
                }
                child->kill_pending = 1;
                remote_kills++;
                event("kill-deferred", child->pid, child->owner);
                return KILL_DEFERRED;
            }
            terminate(child, 137);
            return 0;
        }
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
    case SYS_HART:
        return this_hart()->id;
    case SYS_READ:
        if (current != 0) {
            return E_OWNER;
        }
        if (rx_count != 0) {
            long byte = rx_ring[rx_tail];
            rx_tail = (rx_tail + 1) % RX_CAPACITY;
            tail_wraps += rx_tail == 0;
            rx_consumed++;
            rx_count--;
            return byte;
        }
        process->state = READING;
        read_blocks++;
        *reschedule = 1;
        return 0;
    case SYS_PS:
        for (int i = 0; i < TASK_SLOTS; i++) {
            if (processes[i].state != FREE) {
                event("job", processes[i].pid, processes[i].state);
                event("job-hits", processes[i].pid, processes[i].timer_hits);
                if (processes[i].entry == WORK_SPIN) {
                    volatile struct UserData *data = (void *)(DATA_BASE + i * DATA_SIZE);
                    event("job-progress", processes[i].pid, data->counter);
                }
            }
        }
        return 0;
    case SYS_STATS:
        event("rx-irq", external_irqs, rx_received);
        event("rx-ring", rx_count, rx_dropped);
        event("rx-wait", read_blocks, read_wakes);
        event("rx-wrap", head_wraps, tail_wraps);
        event("rx-consumed", rx_consumed, RX_CAPACITY);
        event("hart-timers", 0, harts[0].timer_traps);
        event("hart-timers", 1, harts[1].timer_traps);
        return 0;
    case SYS_DONE:
        if (current != 0) {
            return E_OWNER;
        }
        if (fs_sync()) {
            fail("shutdown FLUSH failed");
        }
        fs_info();
        uart_puts("shutdown: explicit user request\n");
        finish(0);
    case SYS_FAIL:
        fail("user assertion");
    default:
        return E_ARG;
    }
}
struct TrapFrame *trap_dispatch(struct TrapFrame *frame)
{
    lock_scheduler();
    if (current < 0) {
        if ((frame->status & 256UL) || frame->epc != U_IDLE_LOOP) {
            fail("invalid idle context");
        }
        if (frame->cause == EXTERNAL_CAUSE) {
            console_interrupt();
        } else if (frame->cause == TIMER_CAUSE) {
            this_hart()->timer_traps++;
#ifdef BAD_IRQ
            if (this_hart()->id == 0 && this_hart()->timer_traps > 80 &&
                processes[0].state == READING && external_irqs == 0) {
                event("irq-watchdog", external_irqs, processes[0].state);
                fail("UART IRQ delivery disabled: blocked reader watchdog");
            }
#endif
        } else {
            fail("unexpected idle trap");
        }
        return schedule(0);
    }
    struct Process *process = &processes[current];
    if (process->state != RUNNING || process->owner != this_hart()->id ||
        process->affinity != this_hart()->id) {
        fail("exclusive RUNNING ownership");
    }
    unsigned long low = STACK_BASE + current * STACK_SIZE;
    if ((frame->status & 256UL) != 0 || frame->x[2] < low ||
        frame->x[2] > low + STACK_SIZE || (frame->x[2] & 15UL) != 0) {
        fail("trap privilege or stack");
    }
    process->frame = *frame;
    if (process->kill_pending) {
        event("kill-complete", process->pid, this_hart()->id);
        terminate(process, 137);
        return schedule(0);
    }
    if (frame->cause == TIMER_CAUSE) {
        /* STIP deassertion may lag the stimecmp write: ignore early delivery. */
        if (read_time() < this_hart()->deadline) {
            unlock_scheduler();
            return &process->frame;
        }
        this_hart()->timer_traps++;
        process->timer_hits++;
        if (process->entry == WORK_SPIN && frame->x[4] != 0xdeadbeef) {
            fail("user tp corrupted");
        }
        /* Never increment an asynchronous resume PC. */
        return schedule(1);
    }
    if (frame->cause == EXTERNAL_CAUSE) {
        console_interrupt();
        return schedule(0);
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
    unlock_scheduler();
    return &process->frame;
}
void supervisor_main(unsigned long id, unsigned long stack_top)
{
    struct Hart *hart = &harts[id];
    hart->id = id;
    hart->slot = -1;
    hart->stack_top = stack_top;
    *(struct Hart **)stack_top = hart;
    __asm__ volatile("mv tp, %0" :: "r"(hart) : "memory");
    /* Each executing hart fences locally, including the disk-loaded U image.
       Tasks are pinned; no migration or dynamic loading in this chapter. */
    __asm__ volatile("fence.i" ::: "memory");
    extern void supervisor_trap(void);
    __asm__ volatile("csrw stvec, %0" :: "r"(supervisor_trap));
    __asm__ volatile("csrw sie, %0" :: "r"(544UL));
    idle_frames[id].epc = U_IDLE_LOOP;
    idle_frames[id].status = 0x200000020UL;
    idle_frames[id].x[2] = (unsigned long)&idle_stacks[id][32];
    idle_frames[id].x[4] = 0x1d1e;
    if (id == 0) {
        uart_puts("Lesson 10: disk U shell, PLIC UART RX, dual-hart idle.\n");
        if (fs_mount()) {
            fail("filesystem mount rejected (never autoformat)");
        }
        clear_bytes(U___USER_BSS_START, U___USER_BSS_END);
        /* 16550 DLAB clear, FIFO enabled/reset, RX trigger one byte. */
        serial[3] = 3;
        serial[2] = 7;
        *(volatile unsigned int *)0x0c000028UL = 1;
        *(volatile unsigned int *)0x0c002080UL = 1U << 10;
        *(volatile unsigned int *)0x0c201000UL = 0;
#ifdef BAD_IRQ
        serial[1] = 0;
        /* Negative image: timer watchdog below detects no delivered RX IRQ. */
#else
        serial[1] = 1;
#endif
        lock_scheduler();
        launch(0, 0, 0);
        unlock_scheduler();
        /* Disk data, kernel BSS, user BSS and controller are initialized
           before MSIP1 release. Hart1's boot acquire precedes fence.i/jump. */
        __asm__ volatile("fence iorw, iorw" ::: "memory");
        *(volatile unsigned int *)0x02000004 = 1;
    }
    lock_scheduler();
    event("hart-online", id, stack_top);
    restore_frame(schedule(0));
}
