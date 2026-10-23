#include "syscall.h"

/* Each invocation's locals are on its own stack. There is no per-process
   global-data relocation: writable globals would still be shared. */
volatile struct SharedCounter shared_counter;

static void counter_worker(void)
{
    long hart = syscall2(SYS_HART, 0, 0);
    require(hart == 0 || hart == 1, "counter hart\n");
    __atomic_fetch_add(&shared_counter.arrived, 1, __ATOMIC_ACQ_REL);
    while (__atomic_load_n(&shared_counter.arrived, __ATOMIC_ACQUIRE) != 2) {
        __asm__ volatile("nop");
    }
    for (int iteration = 0; iteration < 4000; iteration++) {
        if (!shared_counter.break_lock) {
            while (__atomic_exchange_n(&shared_counter.lock, 1, __ATOMIC_ACQUIRE)) {
                shared_counter.contention[hart]++;
            }
        }
        /* A real read-modify-write separated by a widened race window. The
           invariant and exact sum detect overlapping critical sections. */
        if (shared_counter.inside != 0) {
            shared_counter.violations++;
        }
        shared_counter.inside++;
        unsigned long before = shared_counter.value;
        if (shared_counter.break_lock && iteration == 0) {
            /* Negative image deliberately omits the critical-section lock.
               Force both first reads BEFORE either store, guaranteeing a lost
               increment instead of treating a probabilistic race/timeout as proof. */
            __atomic_fetch_add(&shared_counter.broken_arrived, 1, __ATOMIC_ACQ_REL);
            while (__atomic_load_n(&shared_counter.broken_arrived, __ATOMIC_ACQUIRE) != 2) {
                __asm__ volatile("nop");
            }
        }
        for (volatile int delay = 0; delay < 50; delay++) {
            __asm__ volatile("nop");
        }
        shared_counter.value = before + 1;
        shared_counter.participants |= 1UL << hart;
        shared_counter.inside--;
        if (!shared_counter.break_lock) {
            __atomic_store_n(&shared_counter.lock, 0, __ATOMIC_RELEASE);
        }
    }
    user_exit(40 + hart);
}

void worker_main(long entry, long argument, volatile struct UserData *data)
{
    if (entry == WORK_COUNTER) {
        counter_worker();
    }
    volatile unsigned long canary = 0x76543210;
    data->canary = 0x76543210;
    if (entry == WORK_SLEEP) {
        say("worker: sleeping\r\n");
        require(sleep_ticks(argument) == 0, "sleep return\n");
        require(canary == 0x76543210, "worker stack\n");
        require(data->canary == 0x76543210, "worker data\n");
        say("worker: woke\r\n");
        user_exit(23);
    }
    if (entry == WORK_EXIT) {
        user_exit(argument);
    }
    if (entry == WORK_OWNER) {
        require(syscall2(SYS_EXIT, 256, 0) == E_ARG, "exit status bounds\n");
        require(wait_child(argument) == E_OWNER, "wait ownership\n");
        require(kill_child(argument) == E_OWNER, "kill ownership\n");
        require(spawn(WORK_EXIT, 1) == E_OWNER, "spawn ownership\n");
        user_exit(31);
    }
    user_exit(99);
}
