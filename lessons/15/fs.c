#include "fs.h"
#include "journal.h"
#include "block.h"
#include "runtime.h"
#include "uart.h"

/* Static bounded caches, not a heap. Serialization is exclusively explicit LE. */
#define NODES 512U
#define BLOCKS 1024U
#define PAYLOAD 4092U
#define DATA_LBA 2048U
#define DEPTH 8U
_Static_assert(257 <= 512, "boot records overlap filesystem");
_Static_assert(515 + NODES <= DATA_LBA, "node pages overlap data pool");
_Static_assert(DATA_LBA + BLOCKS * 8 <= 16384, "data pool exceeds image");
_Static_assert((FS_BYTES + PAYLOAD - 1) / PAYLOAD <= 17, "chain cache too small");
_Static_assert(sizeof(struct FileEntry) == 36, "listing ABI size");
_Static_assert(sizeof(struct ListCursor) == 8, "cursor ABI size");
static unsigned char super[512];
static unsigned char node_bits[512];
static unsigned char data_bits[512];
static unsigned char nodes[NODES][512];
static unsigned char staging[4096];
static unsigned char node_seen[NODES];
static unsigned char data_seen[BLOCKS];
static unsigned chain[17];
static unsigned relocation[BLOCKS + 1];
static unsigned root;
static unsigned files;
static unsigned epoch;
static int healthy;
struct Handle {
    unsigned long generation;
    char name[32];
    unsigned cursor;
    unsigned writable;
    int live;
};
static struct Handle handles[4];

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
static void zero(void *destination, unsigned count)
{
    unsigned char *p = destination;
    for (unsigned i = 0; i < count; i++) {
        p[i] = 0;
    }
}
static void copy(void *destination, const void *source, unsigned count)
{
    unsigned char *to = destination;
    const unsigned char *from = source;
    for (unsigned i = 0; i < count; i++) {
        to[i] = from[i];
    }
}
static int zeros(const unsigned char *p, unsigned count)
{
    for (unsigned i = 0; i < count; i++) {
        if (p[i]) {
            return 0;
        }
    }
    return 1;
}
static int compare(const void *left, const void *right)
{
    const unsigned char *a = left;
    const unsigned char *b = right;
    for (unsigned i = 0; i < 32; i++) {
        if (a[i] != b[i]) {
            return a[i] < b[i] ? -1 : 1;
        }
        if (!a[i]) {
            return 0;
        }
    }
    return 0;
}
static int name_length(const char *name)
{
    for (unsigned i = 0; i < 32; i++) {
        unsigned c = (unsigned char)name[i];
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
static int disk_name(const unsigned char *p, int empty)
{
    if (empty && !p[0]) {
        return zeros(p, 32);
    }
    int length = name_length((const char *)p);
    return length > 0 && zeros(p + length, 32 - length);
}
static int bit(const unsigned char *map, unsigned id)
{
    return (map[(id - 1) / 8] >> ((id - 1) % 8)) & 1;
}
static void set_bit(unsigned char *map, unsigned id, int value)
{
    unsigned mask = 1U << ((id - 1) % 8);
    unsigned char *p = map + (id - 1) / 8;
    if (value) {
        *p |= mask;
    } else {
        *p &= ~mask;
    }
}
static unsigned char *page(unsigned id)
{
    return nodes[id - 1];
}
static unsigned char *entry(unsigned char *p, unsigned index)
{
    unsigned stride = get32(p) == 1 ? 64 : 36;
    return p + 16 + index * stride;
}
static int io(unsigned type, unsigned sector, void *buffer)
{
    if (journal_io(type, sector, buffer)) {
        if (journal_error() != J_LIMIT) {
            healthy = 0;
        }
        return F_IO;
    }
    return 0;
}
static int block_io(unsigned type, unsigned id)
{
    for (unsigned i = 0; i < 8; i++) {
        if (io(type, DATA_LBA + (id - 1) * 8 + i, staging + i * 512)) {
            return F_IO;
        }
    }
    return 0;
}
int fs_sync(void)
{
    if (!healthy || io(4, 0, 0)) {
        return F_IO;
    }
    return 0;
}
static int persist(void)
{
    put32(super + 28, root);
    put32(super + 32, files);
    put32(super + 36, epoch);
    put32(super + 508, journal_crc(super, 508));
    for (unsigned id = 1; id <= NODES; id++) {
        if (bit(node_bits, id) && io(1, 514 + id, page(id))) {
            return F_IO;
        }
    }
    if (io(1, 513, node_bits) || io(1, 514, data_bits) || io(1, 512, super)) {
        return F_IO;
    }
    return fs_sync();
}
static unsigned blocks_for(unsigned size)
{
    return (size + PAYLOAD - 1) / PAYLOAD;
}
/* Validate whole tree before setting healthy, with no disk writes. */
static unsigned checked_files;
static unsigned previous_leaf;
static unsigned leaf_depth;
static int validate_file(unsigned char *r)
{
    unsigned size = get32(r + 32);
    unsigned id = get32(r + 36);
    unsigned tail = get32(r + 40);
    if (size > FS_BYTES || !zeros(r + 44, 20)) {
        return -1;
    }
    unsigned count = blocks_for(size);
    if (!count) {
        return id || tail ? -1 : 0;
    }
    for (unsigned i = 0; i < count; i++) {
        if (!id || id > BLOCKS || !bit(data_bits, id) || data_seen[id - 1]) {
            return -1;
        }
        data_seen[id - 1] = 1;
        if (block_io(0, id)) {
            return -1;
        }
        unsigned next = get32(staging);
        if (i + 1 == count) {
            unsigned used = size - i * PAYLOAD;
            if (id != tail || next || !zeros(staging + 4 + used, PAYLOAD - used)) {
                return -1;
            }
        } else if (!next) {
            return -1;
        }
        id = next;
    }
    return 0;
}
static int validate_node(unsigned id, const unsigned char *low,
                         const unsigned char *high, unsigned depth)
{
    if (!id || id > NODES || depth > DEPTH || node_seen[id - 1] || !bit(node_bits, id)) {
        return -1;
    }
    node_seen[id - 1] = 1;
    unsigned char *p = page(id);
    unsigned type = get32(p);
    unsigned count = get32(p + 4);
    if (get32(p + 12)) {
        return -1;
    }
    if (type == 1) {
        if (count > 7 || !zeros(p + 16 + count * 64, 496 - count * 64)) {
            return -1;
        }
        if (leaf_depth && leaf_depth != depth) {
            return -1;
        }
        leaf_depth = depth;
        if (previous_leaf && get32(page(previous_leaf) + 8) != id) {
            return -1;
        }
        previous_leaf = id;
        for (unsigned i = 0; i < count; i++) {
            unsigned char *r = entry(p, i);
            if (!disk_name(r, 0) || compare(r, low) < 0 ||
                (high && compare(r, high) >= 0) ||
                (i && compare(entry(p, i - 1), r) >= 0) || validate_file(r)) {
                return -1;
            }
            checked_files++;
        }
        return 0;
    }
    if (type != 2 || count < 2 || count > 8 || get32(p + 8) ||
        !zeros(p + 16 + count * 36, 496 - count * 36)) {
        return -1;
    }
    for (unsigned i = 0; i < count; i++) {
        unsigned char *r = entry(p, i);
        if (!disk_name(r, i == 0) || (i == 0 && compare(r, low)) ||
            (i && compare(entry(p, i - 1), r) >= 0) ||
            (high && compare(r, high) >= 0)) {
            return -1;
        }
        const unsigned char *upper = i + 1 < count ? entry(p, i + 1) : high;
        if (validate_node(get32(r + 32), r, upper, depth + 1)) {
            return -1;
        }
    }
    return 0;
}
int fs_mount(void)
{
    healthy = 0;
    zero(handles, sizeof(handles));
    if (block_init() || journal_recover() || io(0, 512, super) || io(0, 513, node_bits) ||
        io(0, 514, data_bits)) {
        return -1;
    }
    static const unsigned char magic[8] = {'B','P','T','F','S','1','2',0};
    for (unsigned i = 0; i < 8; i++) {
        if (super[i] != magic[i]) {
            return -1;
        }
    }
    if (get32(super + 8) != 1 || get32(super + 12) != NODES ||
        get32(super + 16) != BLOCKS || get32(super + 20) != FS_FILES ||
        get32(super + 24) != FS_BYTES || get32(super + 40) != DATA_LBA ||
        !zeros(super + 44, 464) || !journal_identity(super) || !zeros(node_bits + 64, 448) ||
        !zeros(data_bits + 128, 384)) {
        return -1;
    }
    root = get32(super + 28);
    files = get32(super + 32);
    epoch = get32(super + 36);
    if (files > FS_FILES || !epoch) {
        return -1;
    }
    zero(node_seen, sizeof(node_seen));
    zero(data_seen, sizeof(data_seen));
    checked_files = 0;
    previous_leaf = 0;
    leaf_depth = 0;
    for (unsigned id = 1; id <= NODES; id++) {
        if (bit(node_bits, id) && io(0, 514 + id, page(id))) {
            return -1;
        }
    }
    unsigned char lower[32] = {0};
    if (validate_node(root, lower, 0, 1) || checked_files != files ||
        get32(page(previous_leaf) + 8)) {
        return -1;
    }
    for (unsigned id = 1; id <= NODES; id++) {
        if (bit(node_bits, id) != node_seen[id - 1]) {
            return -1;
        }
    }
    for (unsigned id = 1; id <= BLOCKS; id++) {
        if (bit(data_bits, id) != data_seen[id - 1]) {
            return -1;
        }
    }
    healthy = 1;
    uart_puts("fs: mounted BPTFS12 READ WRITE FLUSH\n");
    return 0;
}
static unsigned find_leaf(const char *name)
{
    unsigned id = root;
    for (unsigned depth = 0; depth < DEPTH; depth++) {
        unsigned char *p = page(id);
        if (get32(p) == 1) {
            return id;
        }
        unsigned selected = 0;
        for (unsigned i = 1; i < get32(p + 4); i++) {
            if (compare(name, entry(p, i)) < 0) {
                break;
            }
            selected = i;
        }
        id = get32(entry(p, selected) + 32);
    }
    return 0;
}
static unsigned char *lookup(const char *name)
{
    unsigned id = find_leaf(name);
    if (!id) {
        return 0;
    }
    unsigned char *p = page(id);
    for (unsigned i = 0; i < get32(p + 4); i++) {
        if (!compare(name, entry(p, i))) {
            return entry(p, i);
        }
    }
    return 0;
}
static unsigned allocate_node(unsigned type)
{
    for (unsigned id = 1; id <= NODES; id++) {
        if (!bit(node_bits, id)) {
            set_bit(node_bits, id, 1);
            zero(page(id), 512);
            put32(page(id), type);
            return id;
        }
    }
    return 0;
}
/* Return right sibling ID plus its fence after split. The preflight guarantees
   enough pages for every ancestor and new root before any cache mutation. */
static unsigned insert(unsigned id, const unsigned char *record, unsigned char *fence)
{
    unsigned char *p = page(id);
    unsigned type = get32(p);
    unsigned count = get32(p + 4);
    unsigned stride = type == 1 ? 64 : 36;
    unsigned char combined[9 * 64];
    unsigned position = 0;
    unsigned char addition[64] = {0};
    if (type == 1) {
        while (position < count && compare(entry(p, position), record) < 0) {
            position++;
        }
        copy(addition, record, 64);
    } else {
        while (position + 1 < count && compare(record, entry(p, position + 1)) >= 0) {
            position++;
        }
        unsigned child = get32(entry(p, position) + 32);
        unsigned right = insert(child, record, addition);
        if (!right) {
            return 0;
        }
        put32(addition + 32, right);
        position++;
    }
    for (unsigned i = 0; i < position; i++) {
        copy(combined + i * stride, entry(p, i), stride);
    }
    copy(combined + position * stride, addition, stride);
    for (unsigned i = position; i < count; i++) {
        copy(combined + (i + 1) * stride, entry(p, i), stride);
    }
    count++;
    unsigned capacity = type == 1 ? 7 : 8;
    if (count <= capacity) {
        zero(p + 16, 496);
        copy(p + 16, combined, count * stride);
        put32(p + 4, count);
        return 0;
    }
    unsigned right = allocate_node(type);
    unsigned left_count = count / 2;
    unsigned char *sibling = page(right);
    put32(sibling + 4, count - left_count);
    copy(sibling + 16, combined + left_count * stride, (count - left_count) * stride);
    if (type == 1) {
        put32(sibling + 8, get32(p + 8));
        put32(p + 8, right);
    }
    zero(p + 16, 496);
    copy(p + 16, combined, left_count * stride);
    put32(p + 4, left_count);
    copy(fence, sibling + 16, 32);
    return right;
}
static int create(const char *name)
{
    if (files == FS_FILES || epoch == 0xffffffffU) {
        return F_FULL;
    }
    unsigned id = root;
    unsigned depth = 1;
    unsigned needed = 1;
    unsigned consecutive_full = 0;
    for (;;) {
        unsigned char *p = page(id);
        unsigned count = get32(p + 4);
        unsigned type = get32(p);
        if (count == (type == 1 ? 7U : 8U)) {
            consecutive_full++;
        } else {
            consecutive_full = 0;
        }
        if (type == 1) {
            if (count < 7) {
                needed = 0;
            } else {
                needed = consecutive_full;
                if (consecutive_full == depth) {
                    if (depth == DEPTH) {
                        return F_FULL;
                    }
                    needed++;
                }
            }
            break;
        }
        unsigned selected = 0;
        while (selected + 1 < count && compare(name, entry(p, selected + 1)) >= 0) {
            selected++;
        }
        id = get32(entry(p, selected) + 32);
        depth++;
    }
    unsigned available = 0;
    for (unsigned i = 1; i <= NODES; i++) {
        available += !bit(node_bits, i);
    }
    if (available < needed) {
        return F_FULL;
    }
    unsigned char record[64] = {0};
    copy(record, name, name_length(name));
    unsigned char fence[32];
    unsigned right = insert(root, record, fence);
    if (right) {
        unsigned new_root = allocate_node(2);
        unsigned char *p = page(new_root);
        put32(p + 4, 2);
        put32(entry(p, 0) + 32, root);
        copy(entry(p, 1), fence, 32);
        put32(entry(p, 1) + 32, right);
        root = new_root;
    }
    files++;
    epoch++;
    return persist();
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
static int collect(unsigned char *record)
{
    unsigned count = blocks_for(get32(record + 32));
    unsigned id = get32(record + 36);
    for (unsigned i = 0; i < count; i++) {
        chain[i] = id;
        if (block_io(0, id)) {
            return F_IO;
        }
        id = get32(staging);
    }
    return 0;
}
/* Resize preflights all capacity first. Never returns a fake short success.
   All data changes are staged in the enclosing API transaction. */
static int resize(unsigned char *r, unsigned size)
{
    unsigned old_size = get32(r + 32);
    unsigned old_count = blocks_for(old_size);
    unsigned new_count = blocks_for(size);
    unsigned available = 0;
    for (unsigned id = 1; id <= BLOCKS; id++) {
        available += !bit(data_bits, id);
    }
    if (new_count > old_count && new_count - old_count > available) {
        return F_FULL;
    }
    if (collect(r)) {
        return F_IO;
    }
    for (unsigned i = old_count; i < new_count; i++) {
        for (unsigned id = 1; id <= BLOCKS; id++) {
            if (!bit(data_bits, id)) {
                chain[i] = id;
                set_bit(data_bits, id, 1);
                break;
            }
        }
    }
    for (unsigned i = new_count; i < old_count; i++) {
        set_bit(data_bits, chain[i], 0);
    }
    for (unsigned i = 0; i < new_count; i++) {
        if (i < old_count) {
            if (block_io(0, chain[i])) {
                return F_IO;
            }
        } else {
            zero(staging, sizeof(staging));
        }
        /* Zero newly visible bytes as well as the final unused tail. */
        unsigned begin = i * PAYLOAD;
        unsigned keep = old_size < size ? old_size : size;
        if (keep < begin + PAYLOAD) {
            unsigned offset = keep > begin ? keep - begin : 0;
            zero(staging + 4 + offset, PAYLOAD - offset);
        }
        put32(staging, i + 1 < new_count ? chain[i + 1] : 0);
        if (block_io(1, chain[i])) {
            return F_IO;
        }
    }
    put32(r + 32, size);
    put32(r + 36, new_count ? chain[0] : 0);
    put32(r + 40, new_count ? chain[new_count - 1] : 0);
    return 0;
}
static long mutate_open(const char *name, unsigned mode)
{
    if (name_length(name) < 0 || mode > FS_RW) {
        return F_ARG;
    }
    if (!healthy) {
        return F_IO;
    }
    int slot = -1;
    for (unsigned i = 0; i < 4; i++) {
        if (handles[i].live && !compare(handles[i].name, name)) {
            return F_BUSY;
        }
        if (!handles[i].live && slot < 0) {
            slot = i;
        }
    }
    unsigned char *r = lookup(name);
    if (!r && mode != FS_REPLACE) {
        return F_MISSING;
    }
    if (slot < 0) {
        return F_FULL;
    }
    struct Handle *h = &handles[slot];
    if (h->generation >= 0x1ffffffffffffffeUL) {
        return F_GENERATION;
    }
    if (!r) {
        int result = create(name);
        if (result) {
            return result;
        }
        r = lookup(name);
    } else if (mode == FS_REPLACE) {
        if (epoch == 0xffffffffU) {
            return F_FULL;
        }
        int result = resize(r, 0);
        if (result) {
            return result;
        }
        epoch++;
        if (persist()) {
            return F_IO;
        }
    }
    zero(h->name, 32);
    copy(h->name, name, name_length(name));
    h->generation++;
    h->cursor = 0;
    h->writable = mode != FS_EXISTING;
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
    unsigned char *r = lookup(h->name);
    unsigned size = get32(r + 32);
    if (h->cursor >= size) {
        return 0;
    }
    if (count > size - h->cursor) {
        count = size - h->cursor;
    }
    if (collect(r)) {
        return F_IO;
    }
    unsigned done = 0;
    while (done < count) {
        unsigned position = h->cursor + done;
        unsigned offset = position % PAYLOAD;
        unsigned part = PAYLOAD - offset;
        if (part > count - done) {
            part = count - done;
        }
        if (block_io(0, chain[position / PAYLOAD])) {
            return F_IO;
        }
        copy((unsigned char *)buffer + done, staging + 4 + offset, part);
        done += part;
    }
    h->cursor += count;
    return count;
}
static long write_at(long token, const void *buffer, unsigned count, int append)
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
    unsigned char *r = lookup(h->name);
    unsigned size = get32(r + 32);
    unsigned position = append ? size : h->cursor;
    if (!count) {
        return 0;
    }
    if (count > FS_BYTES - position || epoch == 0xffffffffU) {
        return F_FULL;
    }
    if (position + count > size) {
        int result = resize(r, position + count);
        if (result) {
            return result;
        }
    } else if (collect(r)) {
        return F_IO;
    }
    unsigned done = 0;
    while (done < count) {
        unsigned offset = (position + done) % PAYLOAD;
        unsigned index = (position + done) / PAYLOAD;
        unsigned part = PAYLOAD - offset;
        if (part > count - done) {
            part = count - done;
        }
        if (block_io(0, chain[index])) {
            return F_IO;
        }
        copy(staging + 4 + offset, (const unsigned char *)buffer + done, part);
        if (block_io(1, chain[index])) {
            return F_IO;
        }
        done += part;
    }
    epoch++;
    if (persist()) {
        return F_IO;
    }
    h->cursor = position + count;
    return count;
}
static long mutate_write(long token, const void *buffer, unsigned count)
{
    return write_at(token, buffer, count, 0);
}
static long mutate_append(long token, const void *buffer, unsigned count)
{
    return write_at(token, buffer, count, 1);
}
long fs_seek(long token, unsigned offset)
{
    struct Handle *h = handle(token);
    if (!h) {
        return F_HANDLE;
    }
    if (offset > FS_BYTES) {
        return F_ARG;
    }
    if (!healthy) {
        return F_IO;
    }
    h->cursor = offset;
    return offset;
}
static long mutate_truncate(long token, unsigned size)
{
    struct Handle *h = handle(token);
    if (!h) {
        return F_HANDLE;
    }
    if (!h->writable) {
        return F_MODE;
    }
    if (size > FS_BYTES) {
        return F_ARG;
    }
    if (!healthy) {
        return F_IO;
    }
    if (epoch == 0xffffffffU) {
        return F_FULL;
    }
    int result = resize(lookup(h->name), size);
    if (result) {
        return result;
    }
    epoch++;
    return persist();
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
static long mutate_remove(const char *name)
{
    if (name_length(name) < 0) {
        return F_ARG;
    }
    if (!healthy) {
        return F_IO;
    }
    for (unsigned i = 0; i < 4; i++) {
        if (handles[i].live && !compare(handles[i].name, name)) {
            return F_BUSY;
        }
    }
    unsigned char *r = lookup(name);
    if (!r) {
        return F_MISSING;
    }
    if (epoch == 0xffffffffU) {
        return F_FULL;
    }
    int result = resize(r, 0);
    if (result) {
        return result;
    }
    unsigned char *p = page(find_leaf(name));
    unsigned count = get32(p + 4);
    unsigned index = (unsigned)(r - p - 16) / 64;
    for (unsigned i = index; i + 1 < count; i++) {
        copy(entry(p, i), entry(p, i + 1), 64);
    }
    zero(entry(p, count - 1), 64);
    put32(p + 4, count - 1);
    files--;
    epoch++;
    return persist();
}
static unsigned first_leaf(void)
{
    unsigned id = root;
    while (get32(page(id)) == 2) {
        id = get32(entry(page(id), 0) + 32);
    }
    return id;
}
long fs_list_page(struct FileEntry *out, unsigned capacity, struct ListCursor *cursor)
{
    if (!healthy) {
        return F_IO;
    }
    if (!capacity || capacity > 16 || cursor->index > files ||
        (cursor->epoch ? cursor->epoch != epoch : cursor->index != 0)) {
        return F_ARG;
    }
    unsigned skip = cursor->index;
    unsigned count = 0;
    for (unsigned id = first_leaf(); id && count < capacity; id = get32(page(id) + 8)) {
        unsigned char *p = page(id);
        for (unsigned i = 0; i < get32(p + 4) && count < capacity; i++) {
            if (skip) {
                skip--;
            } else {
                unsigned char *destination = (unsigned char *)out + count * sizeof(*out);
                copy(destination, entry(p, i), 32);
                put32(destination + 32, get32(entry(p, i) + 32));
                count++;
            }
        }
    }
    cursor->epoch = epoch;
    cursor->index += count;
    return count;
}
static long mutate_defrag(void)
{
    if (!healthy) {
        return F_IO;
    }
    for (unsigned i = 0; i < 4; i++) {
        if (handles[i].live) {
            return F_BUSY;
        }
    }
    if (epoch == 0xffffffffU) {
        return F_FULL;
    }
    unsigned used = 0;
    zero(relocation, sizeof(relocation));
    for (unsigned id = 1; id <= BLOCKS; id++) {
        if (bit(data_bits, id)) {
            relocation[id] = ++used;
        }
    }
    for (unsigned id = 1; id <= BLOCKS; id++) {
        if (relocation[id]) {
            if (block_io(0, id)) {
                return F_IO;
            }
            put32(staging, relocation[get32(staging)]);
            if (block_io(1, relocation[id])) {
                return F_IO;
            }
        }
    }
    for (unsigned id = first_leaf(); id; id = get32(page(id) + 8)) {
        unsigned char *p = page(id);
        for (unsigned i = 0; i < get32(p + 4); i++) {
            unsigned char *r = entry(p, i);
            put32(r + 36, relocation[get32(r + 36)]);
            put32(r + 40, relocation[get32(r + 40)]);
        }
    }
    zero(data_bits, sizeof(data_bits));
    for (unsigned id = 1; id <= used; id++) {
        set_bit(data_bits, id, 1);
    }
    epoch++;
    return persist();
}
static void statistic(const char *label, unsigned value)
{
    uart_puts(label);
    print_hex(value);
}
void fs_info(void)
{
    unsigned used = 0;
    unsigned high = 0;
    unsigned logical = 0;
    unsigned node_count = 0;
    for (unsigned id = 1; id <= BLOCKS; id++) {
        if (bit(data_bits, id)) {
            used++;
            high = id;
        }
    }
    for (unsigned id = 1; id <= NODES; id++) {
        node_count += bit(node_bits, id);
    }
    if (healthy) {
        for (unsigned id = first_leaf(); id; id = get32(page(id) + 8)) {
            for (unsigned i = 0; i < get32(page(id) + 4); i++) {
                logical += get32(entry(page(id), i) + 32);
            }
        }
    }
    statistic("fsinfo: logical_bytes=", logical);
    statistic(" allocated_capacity=", used * PAYLOAD);
    statistic(" free_blocks=", BLOCKS - used);
    statistic(" free_bytes=", (BLOCKS - used) * PAYLOAD);
    statistic(" holes=", high - used);
    statistic(" contiguous_tail=", BLOCKS - high);
    statistic(" nodes=", node_count);
    statistic(" files=", files);
    statistic(" reads=", block_reads);
    statistic(" writes=", block_writes);
    statistic(" flushes=", block_flushes);
    statistic(" healthy=", healthy);
    uart_puts("\n");
}

/* The global kernel lock serializes these bounded, non-nested transactions.
 * No disk write occurs until the mutator has returned success. A snapshot is
 * static workspace, not a larger heap; scratch/validation arrays are not state. */
static struct Snapshot {
    unsigned char super[512];
    unsigned char node_bits[512];
    unsigned char data_bits[512];
    unsigned char nodes[NODES][512];
    struct Handle handles[4];
    unsigned root;
    unsigned files;
    unsigned epoch;
} before;
static int transaction_begin(void)
{
    if (!healthy || journal_begin()) {
        return F_IO;
    }
    copy(before.super, super, sizeof(super));
    copy(before.node_bits, node_bits, sizeof(node_bits));
    copy(before.data_bits, data_bits, sizeof(data_bits));
    copy(before.nodes, nodes, sizeof(nodes));
    copy(before.handles, handles, sizeof(handles));
    before.root = root;
    before.files = files;
    before.epoch = epoch;
    return 0;
}
static long transaction_end(long result)
{
    if (result >= 0) {
        int status = journal_commit();
        if (!status) {
            return result;
        }
        result = status;
    }
    if (journal_error() == J_LIMIT) {
        result = F_LIMIT;
    }
    if (journal_error() == J_IO) {
        healthy = 0;
    }
    copy(super, before.super, sizeof(super));
    copy(node_bits, before.node_bits, sizeof(node_bits));
    copy(data_bits, before.data_bits, sizeof(data_bits));
    copy(nodes, before.nodes, sizeof(nodes));
    copy(handles, before.handles, sizeof(handles));
    root = before.root;
    files = before.files;
    epoch = before.epoch;
    journal_abort();
    return result;
}
long fs_open(const char *name, unsigned mode)
{
    if (!healthy) {
        return mutate_open(name, mode);
    }
    if (transaction_begin()) {
        return F_IO;
    }
    return transaction_end(mutate_open(name, mode));
}
long fs_write(long token, const void *buffer, unsigned count)
{
    if (!healthy) {
        return mutate_write(token, buffer, count);
    }
    if (transaction_begin()) {
        return F_IO;
    }
    return transaction_end(mutate_write(token, buffer, count));
}
long fs_append(long token, const void *buffer, unsigned count)
{
    if (!healthy) {
        return mutate_append(token, buffer, count);
    }
    if (transaction_begin()) {
        return F_IO;
    }
    return transaction_end(mutate_append(token, buffer, count));
}
long fs_truncate(long token, unsigned size)
{
    if (!healthy) {
        return mutate_truncate(token, size);
    }
    if (transaction_begin()) {
        return F_IO;
    }
    return transaction_end(mutate_truncate(token, size));
}
long fs_remove(const char *name)
{
    if (!healthy) {
        return mutate_remove(name);
    }
    if (transaction_begin()) {
        return F_IO;
    }
    return transaction_end(mutate_remove(name));
}
long fs_defrag(void)
{
    if (!healthy) {
        return mutate_defrag();
    }
    if (transaction_begin()) {
        return F_IO;
    }
    return transaction_end(mutate_defrag());
}

/* Compose internal mutations under ONE outer transaction. */
long fs_store(const char *name, const void *buffer, unsigned count, int append)
{
    if (name_length(name) < 0 || count > 65536 || (append != 0 && append != 1)) {
        return F_ARG;
    }
    if (!healthy) {
        return F_IO;
    }
    if (append && count == 0) {
        return 0;
    }
    if (transaction_begin()) {
        return F_IO;
    }
    unsigned mode = append && lookup(name) ? FS_RW : FS_REPLACE;
    long token = mutate_open(name, mode);
    long result = token;
    if (token >= 0) {
        unsigned done = 0;
        result = 0;
        while (done < count) {
            unsigned chunk = count - done;
            if (chunk > 4096) {
                chunk = 4096;
            }
            long written = append ? mutate_append(token, (const unsigned char *)buffer + done, chunk) :
                                   mutate_write(token, (const unsigned char *)buffer + done, chunk);
            if (written < 0) {
                result = written;
                break;
            }
            done += chunk;
        }
        /* Private close without fs_sync while journal is active. On error
         * transaction_end restores the complete pre-call handle snapshot. */
        handle(token)->live = 0;
        if (result >= 0) {
            result = count;
        }
    }
    return transaction_end(result);
}
