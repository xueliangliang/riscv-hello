#include "syscall.h"
long syscall2(long number, unsigned long first, unsigned long second)
{
    register unsigned long a0 __asm__("a0") = first;
    register unsigned long a1 __asm__("a1") = second;
    register unsigned long a7 __asm__("a7") = number;
    __asm__ volatile("ecall" : "+r"(a0) : "r"(a1), "r"(a7) : "memory");
    return (long)a0;
}
void say(const char *text)
{
    unsigned long length = 0;
    while (text[length] != 0) {
        length++;
    }
    syscall2(SYS_WRITE, (unsigned long)text, length);
}
long spawn(long entry, long argument)
{
    return syscall2(SYS_SPAWN, entry, argument);
}
long sleep_ticks(long ticks)
{
    return syscall2(SYS_SLEEP, ticks, 0);
}
long wait_child(long pid)
{
    return syscall2(SYS_WAIT, pid, 0);
}
long kill_child(long pid)
{
    return syscall2(SYS_KILL, pid, 0);
}
long state(long pid)
{
    return syscall2(SYS_STATE, pid, 0);
}
long hits(long pid)
{
    return syscall2(SYS_HITS, pid, 0);
}
void user_exit(long status)
{
    syscall2(SYS_EXIT, status, 0);
    for (;;) {
    }
}
void require(int condition, const char *label)
{
    if (!condition) {
        say(label);
        syscall2(SYS_FAIL, 0, 0);
    }
}
