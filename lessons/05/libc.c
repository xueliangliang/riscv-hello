#include "libc.h"

extern unsigned char __heap_start[];
extern unsigned char __heap_end[];
static uintptr_t heap_next;

long mini_write(const void *pointer, size_t length)
{
    return syscall(SYS_WRITE, (uintptr_t)pointer, length);
}

void mini_exit(int status)
{
    (void)syscall(SYS_EXIT, (unsigned long)status, 0);
    for (;;) {
        /* SYS_EXIT must never return. */
    }
}

size_t strlen(const char *text)
{
    size_t length = 0;
    while (text[length] != '\0') {
        length++;
    }
    return length;
}

void *memcpy(void *destination, const void *source, size_t length)
{
    unsigned char *output = destination;
    const unsigned char *input = source;
    for (size_t index = 0; index < length; index++) {
        output[index] = input[index];
    }
    return destination;
}

void *memset(void *destination, int value, size_t length)
{
    unsigned char *output = destination;
    for (size_t index = 0; index < length; index++) {
        output[index] = (unsigned char)value;
    }
    return destination;
}

void *mini_alloc(size_t size)
{
    const uintptr_t end = (uintptr_t)__heap_end;
    if (heap_next == 0) {
        heap_next = (uintptr_t)__heap_start;
    }
    /* Round only after checking the addition; failures never move the bump. */
    if (size == 0 || size > SIZE_MAX - 15U) {
        return NULL;
    }
    size_t aligned_size = (size + 15U) & ~(size_t)15U;
    if (aligned_size > end - heap_next) {
        return NULL;
    }
    void *result = (void *)heap_next;
    heap_next += aligned_size;
    return result;
}
