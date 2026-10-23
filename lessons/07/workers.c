#include "syscall.h"

/* Each invocation's locals are on its own stack. There is no per-process
   global-data relocation: writable globals would still be shared. */
void worker_main(long entry, long argument, volatile struct UserData *data)
{
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
