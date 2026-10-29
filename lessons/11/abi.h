#ifndef LESSON11_ABI_H
#define LESSON11_ABI_H
#define TASK_SLOTS 8
#define STACK_BASE 0x80408000UL
#define STACK_SIZE 4096UL
#define USER_BASE 0x80400000UL
#define USER_DATA_END 0x80407000UL
#define DATA_BASE 0x80407000UL
#define DATA_SIZE 256UL
/* Explicit per-instance data, NOT compiler-relocated .data/.bss globals. */
struct UserData {
    unsigned long counter;
    unsigned long canary;
};
#define SYS_WRITE 1
#define SYS_SPAWN 2
#define SYS_SLEEP 3
#define SYS_EXIT 4
#define SYS_KILL 5
#define SYS_WAIT 6
#define SYS_STATE 7
#define SYS_HITS 8
#define SYS_DONE 9
#define SYS_FAIL 10
#define SYS_HART 11
/* Lesson08 test-only syscall numbers 12/13 are reserved, not reused. */
#define SYS_READ 14
#define SYS_PS 15
#define SYS_STATS 16
#define FREE 0
#define READY 1
#define RUNNING 2
#define SLEEPING 3
#define WAITING 4
#define ZOMBIE 5
#define READING 6
#define E_PID (-1L)
#define E_OWNER (-2L)
#define E_FULL (-3L)
#define E_ARG (-4L)
#define WORK_SPIN 1
#define WORK_SLEEP 2
#define WORK_EXIT 3
#define KILL_DEFERRED 1L
#endif
