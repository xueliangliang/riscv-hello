#include "syscall.h"
long syscall2(long number, unsigned long first, unsigned long second)
{
    return syscall3(number, first, second, 0);
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

long syscall3(long number, unsigned long first, unsigned long second, unsigned long third)
{
    register unsigned long a0 __asm__("a0") = first;
    register unsigned long a1 __asm__("a1") = second;
    register unsigned long a2 __asm__("a2") = third;
    register unsigned long a7 __asm__("a7") = number;
    __asm__ volatile("ecall" : "+r"(a0) : "r"(a1), "r"(a2), "r"(a7) : "memory");
    return (long)a0;
}

long file_open(const char *name, unsigned long mode)
{
    return syscall3(FS_OPEN, (unsigned long)name, mode, 0);
}
long file_read(long handle, void *buffer, unsigned long count)
{
    return syscall3(FS_READ, handle, (unsigned long)buffer, count);
}
long file_write(long handle, const void *buffer, unsigned long count)
{
    return syscall3(FS_WRITE, handle, (unsigned long)buffer, count);
}
long file_flush(long handle)
{
    return syscall2(FS_FLUSH, handle, 0);
}
long file_close(long handle)
{
    return syscall2(FS_CLOSE, handle, 0);
}
long file_remove(const char *name)
{
    return syscall2(FS_REMOVE, (unsigned long)name, 0);
}

long file_append(long h, const void *p, unsigned long n)
{
    return syscall3(FS_APPEND, h, (unsigned long)p, n);
}
long file_seek(long h, unsigned long offset)
{
    return syscall3(FS_SEEK, h, offset, 0);
}
long file_truncate(long h, unsigned long size)
{
    return syscall3(FS_TRUNCATE, h, size, 0);
}
long file_list_page(struct FileEntry *p, unsigned long n, struct ListCursor *c)
{
    return syscall3(FS_LIST_PAGE, (unsigned long)p, n, (unsigned long)c);
}
long file_defrag(void)
{
    return syscall3(FS_DEFRAG, 0, 0, 0);
}
