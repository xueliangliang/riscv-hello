#ifndef LESSON10_RUNTIME_H
#define LESSON10_RUNTIME_H
#include <stdint.h>
#include <stddef.h>
struct TrapFrame {
    uint64_t x[32];
    uint64_t epc;
    uint64_t status;
    uint64_t cause;
    uint64_t value;
};
_Static_assert(sizeof(struct TrapFrame) == 288, "assembly frame size");
_Static_assert(offsetof(struct TrapFrame, epc) == 256, "assembly epc offset");
void finish(int status) __attribute__((noreturn));
void fail(const char *message) __attribute__((noreturn));
void print_hex(uint64_t value);
void restore_frame(struct TrapFrame *frame) __attribute__((noreturn));
struct TrapFrame *trap_dispatch(struct TrapFrame *frame);
#endif
