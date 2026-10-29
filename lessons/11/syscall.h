#ifndef LESSON11_SYSCALL_H
#define LESSON11_SYSCALL_H
#include "abi.h"
#include "fs.h"
long syscall3(long number, unsigned long first, unsigned long second, unsigned long third);
void file_test(int verify);
void file_pressure(void);
/* User API. Counts are checked in S, not silently narrowed in this wrapper. */
long file_open(const char *name, unsigned long mode);
long file_read(long handle, void *buffer, unsigned long count);
long file_write(long handle, const void *buffer, unsigned long count);
long file_flush(long handle);
long file_close(long handle);
long file_remove(const char *name);
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
long file_append(long h, const void *p, unsigned long n);
long file_seek(long h, unsigned long offset);
long file_truncate(long h, unsigned long size);
long file_list_page(struct FileEntry *p, unsigned long n, struct ListCursor *c);
long file_defrag(void);
#endif
