#ifndef LESSON08_ABI_H
#define LESSON08_ABI_H
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
#define FREE 0
#define READY 1
#define RUNNING 2
#define SLEEPING 3
#define WAITING 4
#define ZOMBIE 5
#define E_PID (-1L)
#define E_OWNER (-2L)
#define E_FULL (-3L)
#define E_ARG (-4L)
#define WORK_SPIN 1
#define WORK_SLEEP 2
#define WORK_EXIT 3
#define WORK_OWNER 4
#define WORK_COUNTER 5
#define SYS_HART 11
#define SYS_REMOTE_KILLS 12
#define SYS_IDLE 13
#define KILL_DEFERRED 1L
/* Compiler globals below are deliberately shared by all user instances. */
struct SharedCounter {
    unsigned int lock;
    unsigned int arrived;
    unsigned int break_lock;       /* test-only kernel injection, normally 0 */
    unsigned int broken_arrived;   /* deterministic negative rendezvous */
    unsigned long value;
    unsigned long inside;
    unsigned long violations;
    unsigned long participants;
    unsigned long contention[2];
};
extern volatile struct SharedCounter shared_counter;
#endif
