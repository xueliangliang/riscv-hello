#include "module_loader.h"
#include "syscall.h"
static unsigned char banks[2][DLL_LIMIT] __attribute__((aligned(16)));
static unsigned char staging[DLL_LIMIT];
static Module generation;
static Module active;
static unsigned next_bank;
static unsigned occupied;
static void clear(unsigned char *bytes, unsigned size)
{
    for (unsigned i = 0; i < size; i++) {
        bytes[i] = 0;
    }
}
__attribute__((noinline)) void module_fence(void)
{
#ifdef __riscv
    __asm__ volatile("fence.i" ::: "memory");
#else
    /* Native parser/lifecycle tests never execute RISC-V module code. */
    __asm__ volatile("" ::: "memory");
#endif
}
Module module_load(const char *name)
{
    if (active || generation == ~0UL || !name) {
        return 0;
    }
    clear(staging, sizeof(staging));
    clear(banks[next_bank], DLL_LIMIT);
    long size = syscall3(SYS_READFILE, (unsigned long)name,
                         (unsigned long)staging, sizeof(staging));
    if (size < 0 || !module_valid(staging, size)) {
        clear(staging, sizeof(staging));
        return 0;
    }
    occupied = next_bank;
    for (long i = 0; i < size; i++) {
        banks[occupied][i] = staging[i];
    }
    clear(staging, sizeof(staging));
    module_fence();
    /* No subsequent fallible step: publish only the complete checked image. */
    generation++;
    active = generation;
    next_bank ^= 1;
    return active;
}
unsigned long module_base(Module handle)
{
    if (!handle || handle != active) {
        return 0;
    }
    return (unsigned long)banks[occupied];
}
void *module_symbol(Module handle, const char *name, unsigned signature)
{
    unsigned long base = module_base(handle);
    if (!base || !name || (signature != DLL_UNARY && signature != DLL_BINARY)) {
        return 0;
    }
    const unsigned char *image = (const unsigned char *)base;
    unsigned table = load32(image + 16);
    unsigned count = load32(image + 20);
    for (unsigned i = 0; i < count; i++) {
        const unsigned char *entry = image + table + i * 24;
        if (load32(entry + 20) == signature && export_matches(entry, name)) {
            return (void *)(base + load32(entry + 16));
        }
    }
    return 0;
}
int module_unload(Module handle)
{
    if (!handle || handle != active) {
        return -1;
    }
    active = 0;
    clear(banks[occupied], DLL_LIMIT);
    module_fence();
    return 0;
}
