#include "formats.h"
uint32_t load32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static int magic_matches(const unsigned char *bytes, const char *magic)
{
    for (unsigned i = 0; i < 8; i++) {
        if (bytes[i] != (unsigned char)magic[i]) {
            return 0;
        }
    }
    return 1;
}
int executable_valid(const unsigned char *p, unsigned long size, struct Executable *out)
{
    if (size < EXEC_HEADER || size > APP_LIMIT || !magic_matches(p, "RVEXEC1\0")) {
        return 0;
    }
    uint32_t payload = load32(p + 16);
    uint32_t entry = load32(p + 20);
    uint32_t memory = load32(p + 28);
    uint32_t code = load32(p + 36);
    uint32_t abi = load32(p + 32);
    if (load32(p + 8) != 1 || load32(p + 12) != size ||
        payload != size - EXEC_HEADER || load32(p + 24) != APP_BASE ||
        (abi != 1 && abi != 2) || load32(p + 40) || load32(p + 44)) {
        return 0;
    }
    unsigned memory_limit = abi == 1 ? APP_LIMIT : APP_MEMORY_LIMIT;
    if (code < 2 || (code & 1) || code > payload || payload > memory || memory > memory_limit ||
        (payload & 15) || (memory & 15) || entry > code - 2 || (entry & 1)) {
        return 0;
    }
    out->payload = payload;
    out->entry = entry;
    out->memory = memory;
    out->abi = abi;
    return 1;
}
int export_matches(const unsigned char *field, const char *name)
{
    for (unsigned i = 0; i < 16; i++) {
        if (field[i] != (unsigned char)name[i]) {
            return 0;
        }
        if (!field[i]) {
            return 1;
        }
    }
    return 0;
}
static int name_valid(const unsigned char *name)
{
    unsigned end = 0;
    while (end < 16 && name[end]) {
        if (name[end] < 33 || name[end] > 126) {
            return 0;
        }
        end++;
    }
    if (!end || end == 16) {
        return 0;
    }
    for (; end < 16; end++) {
        if (name[end]) {
            return 0;
        }
    }
    return 1;
}
int module_valid(const unsigned char *p, unsigned long size)
{
    if (size < 32 || size > DLL_LIMIT || (size & 1) || !magic_matches(p, "RVDLL01\0")) {
        return 0;
    }
    uint32_t table = load32(p + 16);
    uint32_t count = load32(p + 20);
    uint32_t code = load32(p + 24);
    if (load32(p + 8) != 1 || load32(p + 12) != size || load32(p + 28) != 1 ||
        !count || count > 8 || table < 32 || (table & 7) ||
        table > size || count > (size - table) / 24 ||
        code < table + count * 24 || code >= size || (code & 1)) {
        return 0;
    }
    for (unsigned i = 0; i < count; i++) {
        const unsigned char *entry = p + table + i * 24;
        uint32_t offset = load32(entry + 16);
        uint32_t signature = load32(entry + 20);
        if (!name_valid(entry) || offset < code || offset >= size || (offset & 1) ||
            (signature != DLL_UNARY && signature != DLL_BINARY)) {
            return 0;
        }
        for (unsigned j = 0; j < i; j++) {
            if (export_matches(p + table + j * 24, (const char *)entry)) {
                return 0;
            }
        }
    }
    return 1;
}
