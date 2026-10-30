#include "journal.h"
#include "block.h"

_Static_assert(1027 <= 2048, "metadata/data overlap");
_Static_assert(2048 + 1024 * 8 <= J_HEADER, "home/log overlap");
_Static_assert(J_IMAGES + J_CAPACITY <= 16384, "log outside device");
static unsigned char images[J_CAPACITY][512];
static unsigned char log_descriptors[8192];
static unsigned char header[512];
static unsigned targets[J_CAPACITY];
static unsigned count;
static int active;
static int error;
static int poisoned;

static unsigned get32(const unsigned char *p)
{
    return (unsigned)p[0] | (unsigned)p[1] << 8 |
           (unsigned)p[2] << 16 | (unsigned)p[3] << 24;
}
static void put32(unsigned char *p, unsigned value)
{
    for (unsigned i = 0; i < 4; i++) {
        p[i] = value >> (8 * i);
    }
}
static void copy(void *destination, const void *source, unsigned size)
{
    unsigned char *to = destination;
    const unsigned char *from = source;
    for (unsigned i = 0; i < size; i++) {
        to[i] = from[i];
    }
}
static void zero(unsigned char *p, unsigned size)
{
    for (unsigned i = 0; i < size; i++) {
        p[i] = 0;
    }
}
static int zeros(const unsigned char *p, unsigned size)
{
    for (unsigned i = 0; i < size; i++) {
        if (p[i]) {
            return 0;
        }
    }
    return 1;
}
unsigned journal_crc(const void *bytes, unsigned length)
{
    const unsigned char *p = bytes;
    unsigned crc = 0xffffffffU;
    for (unsigned i = 0; i < length; i++) {
        crc ^= p[i];
        for (unsigned bit = 0; bit < 8; bit++) {
            crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
        }
    }
    return crc ^ 0xffffffffU;
}
static int magic(const unsigned char *p, const char *expected)
{
    for (unsigned i = 0; i < 8; i++) {
        if (p[i] != (unsigned char)expected[i]) {
            return 0;
        }
    }
    return 1;
}
int journal_identity(const unsigned char *p)
{
    return magic(p, "BPTFS12") && get32(p + 8) == 1 &&
           get32(p + 12) == 512 && get32(p + 16) == 1024 &&
           get32(p + 20) == 512 && get32(p + 24) == 65536 &&
           get32(p + 40) == 2048 && zeros(p + 44, 464) &&
           get32(p + 508) == journal_crc(p, 508);
}
static int home(unsigned sector)
{
    return (sector >= 512 && sector <= 1026) ||
           (sector >= 2048 && sector < 10240);
}
static int raw(unsigned type, unsigned sector, void *buffer)
{
    if (poisoned || block_request(type, sector, buffer)) {
        poisoned = 1;
        error = J_IO;
        return J_IO;
    }
    return 0;
}
__attribute__((weak, noinline)) void journal_hook(unsigned phase, unsigned index)
{
    (void)phase;
    (void)index;
}
int journal_error(void)
{
    return error;
}
int journal_begin(void)
{
    if (active || poisoned) {
        return J_IO;
    }
    active = 1;
    count = 0;
    error = 0;
    return 0;
}
void journal_abort(void)
{
    active = 0;
    count = 0;
    /* An I/O error stays poisoned; a capacity rejection does not. */
    if (error == J_LIMIT && !poisoned) {
        error = 0;
    }
}
int journal_io(unsigned type, unsigned sector, void *buffer)
{
    if (poisoned || error == J_IO) {
        return J_IO;
    }
    if (error) {
        return error;
    }
    if (type == 4) {
        return active ? 0 : raw(type, 0, 0);
    }
    if (!home(sector) || (type != 0 && type != 1)) {
        error = J_IO;
        poisoned = 1;
        return error;
    }
    for (unsigned i = 0; active && i < count; i++) {
        if (targets[i] == sector) {
            if (type == 0) {
                copy(buffer, images[i], 512);
            } else {
                copy(images[i], buffer, 512);
            }
            return 0;
        }
    }
    if (type == 0) {
        return raw(0, sector, buffer);
    }
    if (!active) {
        poisoned = 1;
        error = J_IO;
        return error;
    }
    if (count == J_CAPACITY) {
        error = J_LIMIT;
        return error;
    }
    targets[count] = sector;
    copy(images[count], buffer, 512);
    count++;
    return 0;
}
static int clear_log(void)
{
    zero(header, 512);
    if (raw(1, J_HEADER, header)) {
        return J_IO;
    }
    journal_hook(7, 0);
    if (raw(4, 0, 0)) {
        return J_IO;
    }
    journal_hook(8, 0);
    return 0;
}
int journal_commit(void)
{
    if (!active || error || poisoned) {
        return error ? error : J_IO;
    }
    if (!count) {
        active = 0;
        return 0;
    }
    zero(log_descriptors, sizeof(log_descriptors));
    for (unsigned i = 0; i < count; i++) {
        put32(log_descriptors + i * 8, targets[i]);
        put32(log_descriptors + i * 8 + 4, journal_crc(images[i], 512));
        if (raw(1, J_IMAGES + i, images[i])) {
            return J_IO;
        }
    }
    for (unsigned i = 0; i < 16; i++) {
        if (raw(1, J_DESC + i, log_descriptors + i * 512)) {
            return J_IO;
        }
    }
    journal_hook(1, 0);
    if (raw(4, 0, 0)) {
        return J_IO;
    }
    journal_hook(2, 0);
    zero(header, 512);
    copy(header, "REDO12\0", 8);
    put32(header + 8, 1);
    put32(header + 12, 512);
    put32(header + 16, J_CAPACITY);
    put32(header + 20, count);
    put32(header + 24, journal_crc(log_descriptors, sizeof(log_descriptors)));
    put32(header + 28, 16384);
    put32(header + 32, J_HEADER);
    put32(header + 36, J_IMAGES);
    put32(header + 508, journal_crc(header, 508));
    /* Even a failed header WRITE may have persisted: fail closed. */
    if (raw(1, J_HEADER, header)) {
        return J_IO;
    }
    journal_hook(3, 0);
    if (raw(4, 0, 0)) {
        return J_IO;
    }
    journal_hook(4, 0);
    for (unsigned i = 0; i < count; i++) {
        if (raw(1, targets[i], images[i])) {
            return J_IO;
        }
        journal_hook(5, i + 1);
    }
    if (raw(4, 0, 0)) {
        return J_IO;
    }
    journal_hook(6, 0);
    if (clear_log()) {
        return J_IO;
    }
    active = 0;
    count = 0;
    return 0;
}
int journal_recover(void)
{
    active = 0;
    error = 0;
    poisoned = 0;
    count = 0;
    if (raw(0, 512, header) || !journal_identity(header)) {
        return J_IO;
    }
    if (raw(0, J_HEADER, header)) {
        return J_IO;
    }
    if (zeros(header, 512)) {
        return 0;
    }
    count = get32(header + 20);
    if (!magic(header, "REDO12\0") || get32(header + 8) != 1 ||
        get32(header + 12) != 512 || get32(header + 16) != J_CAPACITY ||
        !count || count > J_CAPACITY || get32(header + 28) != 16384 ||
        get32(header + 32) != J_HEADER || get32(header + 36) != J_IMAGES ||
        !zeros(header + 40, 468) ||
        get32(header + 508) != journal_crc(header, 508)) {
        return J_IO;
    }
    for (unsigned i = 0; i < 16; i++) {
        if (raw(0, J_DESC + i, log_descriptors + i * 512)) {
            return J_IO;
        }
    }
    if (get32(header + 24) != journal_crc(log_descriptors, sizeof(log_descriptors)) ||
        !zeros(log_descriptors + count * 8, sizeof(log_descriptors) - count * 8)) {
        return J_IO;
    }
    for (unsigned i = 0; i < count; i++) {
        targets[i] = get32(log_descriptors + i * 8);
        if (!home(targets[i])) {
            return J_IO;
        }
        for (unsigned j = 0; j < i; j++) {
            if (targets[i] == targets[j]) {
                return J_IO;
            }
        }
        if (raw(0, J_IMAGES + i, images[i]) ||
            get32(log_descriptors + i * 8 + 4) != journal_crc(images[i], 512) ||
            (targets[i] == 512 && !journal_identity(images[i]))) {
            return J_IO;
        }
    }
    /* No home writes above this line, including on a late bad payload. */
    for (unsigned i = 0; i < count; i++) {
        if (raw(1, targets[i], images[i])) {
            return J_IO;
        }
        journal_hook(9, i + 1);
    }
    if (raw(4, 0, 0) || clear_log()) {
        return J_IO;
    }
    count = 0;
    return 0;
}
