#include "syscall.h"

void user_main(long entry, long argument, volatile struct UserData *data)
{
    (void)entry;
    (void)argument;
    volatile unsigned long canary = 0xabcdef;
    data->canary = 0xabcdef;
    say("controller: start\r\n");
    require(syscall2(SYS_HART, 0, 0) == 0, "controller affinity\n");
    require(syscall2(SYS_WRITE, 0, 1) == E_ARG, "null pointer\n");
    require(syscall2(SYS_WRITE, ~0UL - 1, 8) == E_ARG, "wrapped pointer\n");
    require(syscall2(SYS_WRITE, 0x80200000, 8) == E_ARG, "kernel pointer\n");
    require(syscall2(SYS_WRITE, STACK_BASE + STACK_SIZE, 1) == E_ARG,
            "other stack pointer\n");
    require(syscall2(SYS_WRITE, USER_DATA_END - 1, 2) == E_ARG, "range crossing\n");
    require(syscall2(SYS_WRITE, (unsigned long)data, 0) == 0, "own data pointer\n");
    require(syscall2(SYS_WRITE, DATA_BASE + DATA_SIZE, 1) == E_ARG,
            "other data pointer\n");
    require(syscall2(SYS_WRITE, USER_BASE, 257) == E_ARG, "write limit\n");
    require(syscall2(SYS_EXIT, 0, 0) == E_ARG, "controller exit policy\n");
    require(syscall2(999, 0, 0) == E_ARG, "unknown syscall\n");
    require(spawn(999, 0) == E_ARG, "invalid entry\n");
    require(sleep_ticks(0) == E_ARG, "invalid sleep\n");
    require(wait_child(0) == E_PID, "invalid PID\n");
    require(kill_child(999999) == E_PID, "unknown PID\n");
    say("check: invalid inputs rejected\r\n");

    /* Slot parity is explicit affinity: slot1 runs on hart1, slot2 on hart0.
       Both spinners contain only add/store/jump: no yield or ecall. */
    long a = spawn(WORK_SPIN, 0);
    long b = spawn(WORK_SPIN, 0);
    long sleeper = spawn(WORK_SLEEP, 1000);
    require(a > 0 && b > 0 && sleeper > 0, "initial spawn\n");
    sleep_ticks(12);
    require(hits(a) >= 2 && hits(b) >= 2, "timer preemption both harts\n");
    require(state(sleeper) == SLEEPING, "sleep must block only worker\n");
    require(kill_child(a) == KILL_DEFERRED, "remote RUNNING kill must defer\n");
    require(syscall2(SYS_REMOTE_KILLS, 0, 0) == 1, "remote kill evidence\n");
    require(wait_child(a) == 137, "deferred kill completion\n");
    volatile struct UserData *old_data =
        (struct UserData *)(DATA_BASE + (a & 15) * DATA_SIZE);
    unsigned long frozen_counter = old_data->counter;
    require(wait_child(a) == E_PID, "double wait\n");
    require(kill_child(a) == E_PID, "reaped kill\n");
    require(kill_child(sleeper) == 0, "kill sleeping worker\n");
    sleep_ticks(4);
    require(hits(b) >= 3, "other hart stopped progressing\n");
    require(old_data->counter == frozen_counter, "killed data progressed\n");
    require(wait_child(sleeper) == 137, "sleep kill status\n");
    require(kill_child(b) == 0 && wait_child(b) == 137, "local READY kill\n");
    say("check: dual-hart preemption sleep remote-kill completion\r\n");

    long replacement = spawn(WORK_EXIT, 42);
    require(replacement > 0 && replacement != a, "generation reuse\n");
    require(kill_child(a) == E_PID, "stale PID killed replacement\n");
    require(wait_child(replacement) == 42, "blocking wait result\n");
    long owner = spawn(WORK_OWNER, 16);
    require(wait_child(owner) == 31, "ownership worker\n");
    long short_sleep = spawn(WORK_SLEEP, 2);
    require(wait_child(short_sleep) == 23, "sleep wake exit\n");
    require(canary == 0xabcdef && data->canary == 0xabcdef,
            "controller stack/data\n");
    require(syscall2(SYS_IDLE, 0, 0) > 0, "lock-aware idle not exercised\n");
    say("check: wait ownership generation stacks idle\r\n");

    long left = spawn(WORK_COUNTER, 0);
    long right = spawn(WORK_COUNTER, 0);
    require(left > 0 && right > 0, "counter spawn\n");
    require(wait_child(left) == 41, "counter hart1 result\n");
    require(wait_child(right) == 40, "counter hart0 result\n");
    require(shared_counter.value == 8000, "shared counter lost update\n");
    require(shared_counter.arrived == 2 && shared_counter.participants == 3,
            "counter missing participant\n");
    require(shared_counter.inside == 0 && shared_counter.violations == 0,
            "shared critical invariant\n");
    require(shared_counter.contention[0] + shared_counter.contention[1] > 0,
            "no real shared lock contention\n");
    say("check: shared counter 8000, two harts, contention, no overlap\r\n");

    long children[TASK_SLOTS - 1];
    for (int i = 0; i < TASK_SLOTS - 1; i++) {
        children[i] = spawn(WORK_EXIT, 60 + i);
        require(children[i] > 0, "fill slots\n");
    }
    require(spawn(WORK_EXIT, 1) == E_FULL, "live exhaustion\n");
    sleep_ticks(4);
    for (int i = 0; i < TASK_SLOTS - 1; i++) {
        require(state(children[i]) == ZOMBIE, "exit must retain slot\n");
    }
    require(spawn(WORK_EXIT, 1) == E_FULL, "zombie slot reused before wait\n");
    say("check: live and zombie exhaustion\r\n");
    for (int i = 0; i < TASK_SLOTS - 1; i++) {
        require(wait_child(children[i]) == 60 + i, "reap exact status\n");
    }
    long last = spawn(WORK_EXIT, 77);
    require(last > 0 && last != children[0], "relaunch after reap\n");
    require(wait_child(children[0]) == E_PID, "stale wait\n");
    require(wait_child(last) == 77, "relaunch status\n");
    say("check: reap relaunch complete\r\n");
    syscall2(SYS_DONE, 0, 0);
    syscall2(SYS_FAIL, 0, 0);
    for (;;) {
    }
}
