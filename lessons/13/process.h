#ifndef LESSON13_PROCESS_H
#define LESSON13_PROCESS_H
#include "runtime.h"
#include "abi.h"
struct Process {
    struct TrapFrame frame;
    unsigned long generation;
    long pid;
    long parent;
    int state;
    long status;
    long waiting_for;
    unsigned long wake_at;
    unsigned long timer_hits;
    unsigned long previous_progress;
    int entry;
    int affinity;
    int owner;
    int kill_pending;
};
extern struct Process processes[TASK_SLOTS];
struct Hart {
    unsigned long stack_top; /* offset 0, consumed by trap.S */
    int id;
    int slot;
    unsigned long deadline;
    unsigned long timer_switches;
    unsigned long timer_traps;
    unsigned long idle_passes;
};
extern struct Hart harts[2];
static inline struct Hart *this_hart(void)
{
    struct Hart *hart;
    __asm__ volatile("mv %0, tp" : "=r"(hart));
    return hart;
}
#define current (this_hart()->slot)
#endif
