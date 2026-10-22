#include "libc.h"

extern unsigned char __heap_start[];
extern unsigned char __heap_end[];
extern void user_bad_trap(void);
static volatile unsigned long bss_probe;
static volatile unsigned long data_probe = 0x505;

static void require(int condition)
{
    if (condition == 0) {
        mini_exit(1);
    }
}

static void say(const char *text)
{
    size_t length = strlen(text);
    require(mini_write(text, length) == (long)length);
}

static void test_write_rejections(void)
{
    require(mini_write(NULL, 1) == ERR_FAULT);
    require(mini_write(NULL, 0) == ERR_FAULT);
    require(mini_write((void *)0x803fffffUL, 1) == ERR_FAULT);
    require(mini_write((void *)0x80410000UL, 1) == ERR_FAULT);
    require(mini_write((void *)0x8040ffffUL, 2) == ERR_FAULT);
    require(mini_write((void *)(UINTPTR_MAX - 7U), 16) == ERR_FAULT);
    require(mini_write((void *)0x80400000UL, WRITE_MAX + 1) == ERR_INVALID);
    require(mini_write((void *)0x80400000UL, SIZE_MAX) == ERR_INVALID);
    require(mini_write((void *)0x80400000UL, 0) == 0);
    require(mini_write((void *)0x80410000UL, 0) == 0);
    require(syscall(99, 0, 0) == ERR_NOSYS);
    say("user: write bounds and unknown syscall rejected.\r\n");
}

static void test_libc_and_heap(void)
{
    const uintptr_t start = (uintptr_t)__heap_start;
    const uintptr_t end = (uintptr_t)__heap_end;
    require(mini_alloc(0) == NULL);
    require(mini_alloc(SIZE_MAX) == NULL);
    require(mini_alloc(SIZE_MAX - 7U) == NULL);
    require(mini_alloc(end - start + 16U) == NULL);
    unsigned char *first = mini_alloc(1);
    unsigned char *second = mini_alloc(17);
    unsigned char *third = mini_alloc(1);
    require((uintptr_t)first == start);
    require((uintptr_t)second == start + 16U);
    require((uintptr_t)third == start + 48U);
    require(((uintptr_t)first & 15U) == 0);
    require(((uintptr_t)second & 15U) == 0);
    require(((uintptr_t)third & 15U) == 0);
    *first = 0x5a;
    *third = 0xa5;
    require(memset(second, 0x141, 17) == second);
    for (size_t index = 0; index < 17; index++) {
        require(second[index] == 'A');
    }
    require(memcpy(second, "hello", 6) == second);
    require(strlen((char *)second) == 5);
    require(strlen("") == 0);
    require(memcpy(second, "", 0) == second);
    require(memset(second, 0, 0) == second);
    require(second[0] == 'h');
    require(second[5] == 0);
    require(*first == 0x5a && *third == 0xa5);
    size_t remaining = end - ((uintptr_t)third + 16U);
    unsigned char *last = mini_alloc(remaining);
    require((uintptr_t)last == start + 64U);
    last[remaining - 1U] = 0x7e;
    require(last[remaining - 1U] == 0x7e);
    require(mini_alloc(1) == NULL);
    require(mini_alloc(16) == NULL);
    require(mini_alloc(SIZE_MAX) == NULL);
    require(*first == 0x5a && *third == 0xa5);
    say("user: libc, aligned heap, overflow and exhaustion verified.\r\n");
}

int user_main(void)
{
#ifdef BAD_TRAP
    user_bad_trap();
#endif
    require(bss_probe == 0);
    require(data_probe == 0x505);
    say("user: hello via syscall.\r\n");
    test_write_rejections();
    test_libc_and_heap();
    say("user: exiting.\r\n");
#ifdef BAD_EXIT
    return 7;
#else
    return 0;
#endif
}
