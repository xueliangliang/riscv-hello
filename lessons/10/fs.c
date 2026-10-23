#include "fs.h"
#include "block.h"
#include "runtime.h"
#include "uart.h"
#include <stdint.h>
/* Disk bytes, never native C structure serialization. See FORMAT.md. */
#define META_LBA 512U
#define DATA_LBA 1024U
_Static_assert(1 + 128 + 128 <= META_LBA, "boot slots overlap metadata");
_Static_assert(META_LBA + 3 <= DATA_LBA, "metadata overlaps extents");
_Static_assert(DATA_LBA + 16 * 8 <= 4096, "extents exceed disk");
static unsigned char metadata[1536];
static unsigned char staging[4096];
static int healthy;
struct Handle {
    unsigned long generation;
    unsigned file;
    unsigned cursor;
    unsigned writable;
    int live;
};
static struct Handle handles[4];
static uint32_t get32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static void put32(unsigned char *p, uint32_t value)
{
    for (unsigned i = 0; i < 4; i++) {
        p[i] = value >> (i * 8);
    }
}
static unsigned char *record(unsigned file)
{
    return metadata + 512 + file * 64;
}
static void zero(unsigned char *p, unsigned count)
{
    for (unsigned i = 0; i < count; i++) {
        p[i] = 0;
    }
}
static int same(const unsigned char *a, const char *b)
{
    for (unsigned i = 0; i < 32; i++) {
        if (a[i] != (unsigned char)b[i]) {
            return 0;
        }
        if (!a[i]) {
            return 1;
        }
    }
    return 0;
}
static int name_length(const char *name)
{
    for (unsigned i = 0; i < 32; i++) {
        unsigned char c = name[i];
        if (!c) {
            return i ? (int)i : -1;
        }
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.')) {
            return -1;
        }
    }
    return -1;
}
static int io(unsigned type, unsigned sector, void *buffer)
{
    if (block_request(type, sector, buffer)) {
        healthy = 0;
        return -1;
    }
    return 0;
}
int fs_mount(void)
{
    healthy = 0;
    if (block_init()) {
        uart_puts("fs: device feature/init failure\n");
        return -1;
    }
    for (unsigned i = 0; i < 3; i++) {
        if (io(0, META_LBA + i, metadata + i * 512)) {
            return -1;
        }
    }
    static const unsigned char header[] = {
        'F','L','A','T','F','S','1','0', 1,0,0,0, 16,0,0,0,
        64,0,0,0, 0,16,0,0, 0,4,0,0, 0,16,0,0
    };
    for (unsigned i = 0; i < 512; i++) {
        unsigned expected = i < sizeof(header) ? header[i] : 0;
        if (metadata[i] != expected) {
            return -1;
        }
    }
    for (unsigned i = 0; i < 16; i++) {
        unsigned char *r = record(i);
        uint32_t used = get32(r + 32);
        if (!used) {
            for (unsigned j = 0; j < 64; j++) {
                if (r[j]) {
                    return -1;
                }
            }
            continue;
        }
        int length = name_length((const char *)r);
        if (used != 1 || length < 0 || get32(r + 36) > 4096 ||
            get32(r + 40) != DATA_LBA + i * 8) {
            return -1;
        }
        for (unsigned j = length; j < 32; j++) {
            if (r[j]) {
                return -1;
            }
        }
        for (unsigned j = 44; j < 64; j++) {
            if (r[j]) {
                return -1;
            }
        }
        for (unsigned j = 0; j < i; j++) {
            if (get32(record(j) + 32) && same(record(j), (const char *)r)) {
                return -1;
            }
        }
    }
    healthy = 1;
    uart_puts("fs: mounted FlatFS10 READ WRITE FLUSH\n");
    return 0;
}
static struct Handle *handle(long token)
{
    if (token < 4) {
        return 0;
    }
    struct Handle *h = &handles[(unsigned long)token % 4];
    if (!h->live || h->generation != (unsigned long)token / 4) {
        return 0;
    }
    return h;
}
int fs_sync(void)
{
    if (!healthy || io(4, 0, 0)) {
        return F_IO;
    }
    return 0;
}
static int persist_metadata(void)
{
    for (unsigned i = 0; i < 3; i++) {
        if (io(1, META_LBA + i, metadata + i * 512)) {
            return F_IO;
        }
    }
    return fs_sync();
}
long fs_open(const char *name, unsigned mode)
{
    int length = name_length(name);
    if (length < 0 || mode > 1) {
        return F_ARG;
    }
    if (!healthy) {
        return F_IO;
    }
    int file = -1;
    int empty = -1;
    int slot = -1;
    for (unsigned i = 0; i < 16; i++) {
        if (!get32(record(i) + 32)) {
            if (empty < 0) {
                empty = i;
            }
        } else if (same(record(i), name)) {
            file = i;
        }
    }
    for (unsigned i = 0; i < 4; i++) {
        if (handles[i].live && handles[i].file == (unsigned)file) {
            return F_BUSY;
        }
        if (!handles[i].live && slot < 0) {
            slot = i;
        }
    }
    if (file < 0 && mode == FS_EXISTING) {
        return F_MISSING;
    }
    if (slot < 0 || (file < 0 && empty < 0)) {
        return F_FULL;
    }
    struct Handle *h = &handles[slot];
    /* Never wrap a generation into a previously issued token. */
    if (h->generation >= 0x1ffffffffffffffeUL) {
        return F_GENERATION;
    }
    if (mode == FS_REPLACE) {
        if (file < 0) {
            file = empty;
        }
        unsigned char *r = record(file);
        zero(r, 64);
        for (int i = 0; i < length; i++) {
            r[i] = name[i];
        }
        put32(r + 32, 1);
        put32(r + 40, DATA_LBA + file * 8);
        if (persist_metadata()) {
            return F_IO;
        }
    }
    h->generation++;
    h->file = file;
    h->cursor = 0;
    h->writable = mode;
    h->live = 1;
    return h->generation * 4 + slot;
}
long fs_read(long token, void *buffer, unsigned count)
{
    struct Handle *h = handle(token);
    if (!h) {
        return F_HANDLE;
    }
    if (count > 4096) {
        return F_ARG;
    }
    if (!healthy) {
        return F_IO;
    }
    unsigned size = get32(record(h->file) + 36);
    unsigned remaining = size - h->cursor;
    if (count > remaining) {
        count = remaining;
    }
    if (!count) {
        return 0;
    }
    for (unsigned i = 0; i < 8; i++) {
        if (io(0, DATA_LBA + h->file * 8 + i, staging + i * 512)) {
            return F_IO;
        }
    }
    for (unsigned i = 0; i < count; i++) {
        ((unsigned char *)buffer)[i] = staging[h->cursor + i];
    }
    h->cursor += count;
    return count;
}
long fs_write(long token, const void *buffer, unsigned count)
{
    struct Handle *h = handle(token);
    if (!h) {
        return F_HANDLE;
    }
    if (!h->writable) {
        return F_MODE;
    }
    if (count > 4096) {
        return F_ARG;
    }
    if (!healthy) {
        return F_IO;
    }
    /* Each write REPLACES the complete logical file, not cursor append. */
    zero(staging, 4096);
    for (unsigned i = 0; i < count; i++) {
        staging[i] = ((const unsigned char *)buffer)[i];
    }
    for (unsigned i = 0; i < 8; i++) {
        if (io(1, DATA_LBA + h->file * 8 + i, staging + i * 512)) {
            return F_IO;
        }
    }
    put32(record(h->file) + 36, count);
    if (persist_metadata()) {
        return F_IO;
    }
    h->cursor = 0;
    return count;
}
long fs_flush(long token)
{
    if (!handle(token)) {
        return F_HANDLE;
    }
    return fs_sync();
}
long fs_close(long token)
{
    struct Handle *h = handle(token);
    if (!h) {
        return F_HANDLE;
    }
    int result = fs_sync();
    h->live = 0;
    return result;
}
long fs_remove(const char *name)
{
    if (name_length(name) < 0) {
        return F_ARG;
    }
    if (!healthy) {
        return F_IO;
    }
    for (unsigned i = 0; i < 16; i++) {
        if (get32(record(i) + 32) && same(record(i), name)) {
            for (unsigned j = 0; j < 4; j++) {
                if (handles[j].live && handles[j].file == i) {
                    return F_BUSY;
                }
            }
            zero(record(i), 64);
            return persist_metadata();
        }
    }
    return F_MISSING;
}
int fs_list(void)
{
    if (!healthy) {
        uart_puts("fs: unavailable\n");
        return F_IO;
    }
    for (unsigned i = 0; i < 16; i++) {
        if (get32(record(i) + 32)) {
            uart_puts("file: ");
            uart_puts((const char *)record(i));
            uart_puts(" size=");
            print_hex(get32(record(i) + 36));
            uart_puts("\n");
        }
    }
    return 0;
}
void fs_info(void)
{
    uart_puts("fsinfo: reads=");
    print_hex(block_reads);
    uart_puts(" writes=");
    print_hex(block_writes);
    uart_puts(" flushes=");
    print_hex(block_flushes);
    uart_puts(" healthy=");
    print_hex(healthy);
    uart_puts("\n");
}
