#ifndef LESSON07_SYSCALL_H
#define LESSON07_SYSCALL_H
#include "abi.h"
long syscall2(long number, unsigned long first, unsigned long second);
void say(const char *text);
long spawn(long entry, long argument);
long sleep_ticks(long ticks);
long wait_child(long pid);
long kill_child(long pid);
long state(long pid);
long hits(long pid);
void user_exit(long status) __attribute__((noreturn));
void require(int condition, const char *label);
#endif
