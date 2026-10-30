#ifndef LESSON14_FORMATS_H
#define LESSON14_FORMATS_H
#include <stdint.h>
#define APP_BASE 0x80500000UL
#define APP_LIMIT 65536U
#define EXEC_HEADER 48U
#define DLL_LIMIT 4096U
#define DLL_UNARY 1U
#define DLL_BINARY 2U
struct Executable {
    uint32_t payload;
    uint32_t entry;
    uint32_t memory;
};
uint32_t load32(const unsigned char *bytes);
int executable_valid(const unsigned char *bytes, unsigned long size, struct Executable *out);
int module_valid(const unsigned char *bytes, unsigned long size);
int export_matches(const unsigned char *field, const char *name);
#endif
