#ifndef LESSON04_RUNTIME_H
#define LESSON04_RUNTIME_H
#include <stdint.h>
#include <stddef.h>

/* x[0..31], then the four supervisor trap CSRs; matches trap.S. */
struct TrapFrame {
    uint64_t x[32];
    uint64_t epc;
    uint64_t status;
    uint64_t cause;
    uint64_t value;
};
_Static_assert(sizeof(struct TrapFrame) == 288, "trap frame size");
_Static_assert(offsetof(struct TrapFrame, epc) == 256, "trap CSR offset");
#define USER_BASE 0x80400000UL
#define USER_END 0x80410000UL
#define USER_STACK_BOTTOM 0x8040c000UL
#define USER_STACK_TOP USER_END
void supervisor_main(void) __attribute__((noreturn));
void trap_dispatch(struct TrapFrame *frame);
void enter_user(void) __attribute__((noreturn));
void finish(int status) __attribute__((noreturn));
void fail(const char *message) __attribute__((noreturn));
void print_hex(uint64_t value);
void report_trap(const struct TrapFrame *frame);
void check_user_trap(const struct TrapFrame *frame);
#endif
