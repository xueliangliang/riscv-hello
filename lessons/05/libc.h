#ifndef LESSON05_LIBC_H
#define LESSON05_LIBC_H
#include <stddef.h>
#include <stdint.h>
#include "abi.h"
long syscall(unsigned long number, unsigned long arg0, unsigned long arg1);
long mini_write(const void *pointer, size_t length);
void mini_exit(int status) __attribute__((noreturn));
size_t strlen(const char *text);
void *memcpy(void *destination, const void *source, size_t length);
void *memset(void *destination, int value, size_t length);
void *mini_alloc(size_t size);
#endif
