#include "module_loader.h"
#include "syscall.h"
typedef double (*Unary)(double);
typedef double (*Binary)(double, double);
union Bits {
    double number;
    unsigned long bits;
};
static unsigned char bss_probe[64];
static unsigned char snapshot_probe[4096];
static const unsigned long inputs[] = {
    0x4004000000000000UL, 0xc004000000000000UL, /* +/-2.5 */
    0x3fe0000000000000UL, 0xbfe0000000000000UL, /* +/-0.5 */
    0x4000000000000000UL, 0xc000000000000000UL, /* exact */
    0, 0x8000000000000000UL, 0x4330000000000000UL,
    1, 0x8000000000000001UL, 0x7ff0000000000000UL,
    0xfff0000000000000UL, 0x7ff8000000000123UL,
    0x7ff0000000000001UL, 0x432fffffffffffffUL
};
static char *append(char *out, const char *text)
{
    while (*text) {
        *out++ = *text++;
    }
    return out;
}
static char *hex(char *out, unsigned long value)
{
    for (int shift = 60; shift >= 0; shift -= 4) {
        *out++ = "0123456789abcdef"[(value >> shift) & 15];
    }
    return out;
}
static void record(const char *label, unsigned long a, unsigned long b, unsigned long c)
{
    char line[160];
    char *out = append(line, label);
    *out++ = ' ';
    out = hex(out, a);
    *out++ = ' ';
    out = hex(out, b);
    *out++ = ' ';
    out = hex(out, c);
    *out++ = '\n';
    *out = 0;
    say(line);
}
__attribute__((noinline)) void module_call_checkpoint(unsigned long base, unsigned long pointer,
                                                      unsigned long result)
{
    __asm__ volatile("" :: "r"(base), "r"(pointer), "r"(result) : "memory");
}
static unsigned long call_symbol(void *pointer, unsigned signature, unsigned long a, unsigned long b)
{
    union Bits left;
    union Bits right;
    union Bits result;
    left.bits = a;
    right.bits = b;
    if (signature == DLL_UNARY) {
        result.number = ((Unary)pointer)(left.number);
    } else {
        result.number = ((Binary)pointer)(left.number, right.number);
    }
    return result.bits;
}
int app_main(void)
{
    for (unsigned i = 0; i < sizeof(bss_probe); i++) {
        require(!bss_probe[i], "FAIL fresh executable BSS\n");
        bss_probe[i] = 0xa5;
    }
    record("APP", syscall2(SYS_HART, 0, 0), APP_BASE, sizeof(bss_probe));
    require(syscall3(FS_OPEN, 0, FS_REPLACE, 0) == E_OWNER, "FAIL app handle owner\n");
    require(syscall2(SYS_EXEC, 0, 0) == E_OWNER, "FAIL app exec owner\n");
    require(syscall3(SYS_READFILE, 0, (unsigned long)snapshot_probe, sizeof(snapshot_probe)) == E_ARG,
            "FAIL snapshot filename pointer\n");
    require(syscall3(SYS_READFILE, (unsigned long)"math.dll", ~0UL, 4) == E_ARG,
            "FAIL snapshot destination overflow\n");
    require(syscall3(SYS_READFILE, APP_BASE + APP_LIMIT - 1, (unsigned long)snapshot_probe, 4) == E_ARG,
            "FAIL snapshot name boundary\n");
    for (unsigned i = 0; i < sizeof(snapshot_probe); i++) {
        snapshot_probe[i] = 0x6d;
    }
    require(syscall3(SYS_READFILE, (unsigned long)"math.dll", (unsigned long)snapshot_probe, 1) == F_LIMIT,
            "FAIL snapshot capacity\n");
    require(syscall3(SYS_READFILE, (unsigned long)"missing.dll", (unsigned long)snapshot_probe, 4096) == F_MISSING,
            "FAIL missing snapshot\n");
    for (unsigned i = 0; i < sizeof(snapshot_probe); i++) {
        require(snapshot_probe[i] == 0x6d, "FAIL failed snapshot partial copy\n");
    }
    for (unsigned i = 0; i < 16; i++) {
        char name[] = "bad00.dll";
        name[3] = '0' + i / 10;
        name[4] = '0' + i % 10;
        require(!module_load(name), "FAIL malformed candidate activated\n");
    }
    const char *names[] = {"ceil", "floor", "max", "min"};
    unsigned long previous_base = 0;
    Module stale = 0;
    for (unsigned round = 0; round < 2; round++) {
        Module handle = module_load("math.dll");
        if (!handle) {
            say("MODULE_MISSING_OR_INVALID\n");
            return 41;
        }
        unsigned long base = module_base(handle);
        require(base && base != previous_base, "FAIL two PIC banks\n");
        require(!module_load("math.dll"), "FAIL second active load accepted\n");
        require(!module_symbol(stale, "ceil", DLL_UNARY), "FAIL stale reloaded handle\n");
        require(!module_symbol(handle, "absent", DLL_UNARY), "FAIL missing symbol\n");
        require(!module_symbol(handle, "ceil", DLL_BINARY), "FAIL wrong signature\n");
        require(!module_symbol(handle, "ceil", 99), "FAIL unknown signature\n");
        record("MODULE", round, handle, base);
        for (unsigned n = 0; n < 4; n++) {
            unsigned signature = n < 2 ? DLL_UNARY : DLL_BINARY;
            void *pointer = module_symbol(handle, names[n], signature);
            require(pointer != 0, "FAIL required export\n");
            char label[32];
            char *end = append(label, "SYMBOL ");
            end = append(end, names[n]);
            *end = 0;
            record(label, signature, base, (unsigned long)pointer);
            for (unsigned i = 0; i < sizeof(inputs) / sizeof(inputs[0]); i++) {
                unsigned long a = inputs[i];
                unsigned long b = inputs[(i + 7) % (sizeof(inputs) / sizeof(inputs[0]))];
                unsigned long got = call_symbol(pointer, signature, a, b);
                module_call_checkpoint(base, (unsigned long)pointer, got);
                end = append(label, "CALL ");
                end = append(end, names[n]);
                *end = 0;
                record(label, a, b, got);
            }
        }
        stale = handle;
        previous_base = base;
        require(!module_unload(handle), "FAIL unload\n");
        require(!module_symbol(handle, "ceil", DLL_UNARY), "FAIL stale unloaded handle\n");
        require(module_unload(handle) < 0, "FAIL repeated unload\n");
        for (unsigned i = 0; i < DLL_LIMIT; i++) {
            require(!((const unsigned char *)base)[i], "FAIL uncleared module bank\n");
        }
    }
    say("CHECK BSS snapshot owner negatives active stale unload two-bases OK\n");
    return 37;
}
