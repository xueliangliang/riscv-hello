#ifndef LESSON07_PROCESS_H
#define LESSON07_PROCESS_H
#include "runtime.h"
#include "abi.h"
/* Process state is independent of hart execution state. Lesson07 has one
   hart and interrupts masked throughout S code; lesson08 must add locking
   and per-hart current/kernel stack before using this table concurrently. */
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
};
extern struct Process processes[TASK_SLOTS];
extern int current;
#endif
