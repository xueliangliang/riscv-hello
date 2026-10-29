#include "syscall.h"
static unsigned char buffer[4096];
static struct FileEntry listing[16];
static unsigned char pattern(unsigned seed, unsigned position)
{
    return (position * 37 + seed * 19 + (position >> 8)) & 255;
}
static void name_for(char *name, unsigned index)
{
    name[0] = 'f';
    name[1] = '0' + index / 100;
    name[2] = '0' + index / 10 % 10;
    name[3] = '0' + index % 10;
    name[4] = 0;
}
static int same(const char *a, const char *b)
{
    while (*a && *a == *b) {
        a++;
        b++;
    }
    return *a == *b;
}
static void close_checked(long h)
{
    require(file_close(h) == 0, "FAIL close\n");
    require(file_close(h) == F_HANDLE, "FAIL stale close\n");
}
static void create_pattern(const char *name, unsigned size, unsigned seed)
{
    long h = file_open(name, FS_REPLACE);
    require(h >= 4, "FAIL create\n");
    unsigned offset = 0;
    while (offset < size) {
        unsigned count = size - offset;
        if (count > 4093) {
            count = 4093;
        }
        for (unsigned i = 0; i < count; i++) {
            buffer[i] = pattern(seed, offset + i);
        }
        require(file_write(h, buffer, count) == count, "FAIL write count\n");
        offset += count;
    }
    require(file_flush(h) == 0, "FAIL flush\n");
    close_checked(h);
}
static unsigned final_size(unsigned index)
{
    if (index % 10 == 2) {
        return index + 500;
    }
    return 8200 + index * 3;
}
static int retained(unsigned index)
{
    return index % 5 != 2 || index % 10 == 2;
}
static unsigned char edge_byte(unsigned position)
{
    if (position >= 5000 && position < 5037) {
        return pattern(253, position - 5000);
    }
    if (position >= 5037 && position < 5048) {
        return pattern(254, position - 5037);
    }
    return 0;
}
static void verify_pattern(const char *name, unsigned size, unsigned seed, int edge)
{
    long h = file_open(name, FS_EXISTING);
    require(h >= 4, "FAIL existing\n");
    unsigned offset = 0;
    while (offset < size) {
        unsigned count = size - offset;
        if (count > 257) {
            count = 257;
        }
        require(file_read(h, buffer, count) == count, "FAIL read count\n");
        for (unsigned i = 0; i < count; i++) {
            unsigned char expected = edge ? edge_byte(offset + i) : pattern(seed, offset + i);
            require(buffer[i] == expected, "FAIL bytes\n");
        }
        offset += count;
    }
    buffer[0] = 0xa5;
    require(file_read(h, buffer, 1) == 0 && buffer[0] == 0xa5, "FAIL EOF\n");
    require(file_write(h, buffer, 1) == F_MODE, "FAIL readonly mode\n");
    close_checked(h);
}
static void page_check(void)
{
    struct ListCursor cursor = {0, 0};
    unsigned expected = 0;
    unsigned position = 0;
    for (;;) {
        unsigned capacity = position % 16 + 1;
        long count = file_list_page(listing, capacity, &cursor);
        require(count >= 0 && count <= capacity, "FAIL page count\n");
        if (!count) {
            break;
        }
        for (long i = 0; i < count; i++) {
            char name[8];
            unsigned size;
            if (!position) {
                name[0] = 'e';
                name[1] = 'd';
                name[2] = 'g';
                name[3] = 'e';
                name[4] = 0;
                size = 8190;
            } else {
                while (expected < 224 && !retained(expected)) {
                    expected++;
                }
                if (expected < 224) {
                    name_for(name, expected);
                    size = final_size(expected++);
                } else {
                    name[0] = 'm';
                    name[1] = 'a';
                    name[2] = 'x';
                    name[3] = 0;
                    size = 65536;
                    require(expected == 224, "FAIL extra entry\n");
                    expected++;
                }
            }
            require(same(name, listing[i].name) && listing[i].size == size, "FAIL page order/size\n");
            position++;
        }
    }
    require(expected == 225 && cursor.index == position, "FAIL page EOF count\n");
    say("fsverify: ordered bounded pages PASS\n");
}
static void fill(unsigned seed, unsigned count)
{
    for (unsigned i = 0; i < count; i++) {
        buffer[i] = pattern(seed, i);
    }
}
static void edge_operations(void)
{
    create_pattern("edge", 12293, 250);
    long h = file_open("edge", FS_RW);
    require(h >= 4, "FAIL edge RW\n");
    require(file_seek(h, 12293) == 12293, "FAIL seek\n");
    require(file_truncate(h, 4092) == 0, "FAIL truncate boundary\n");
    buffer[0] = 0xa5;
    require(file_read(h, buffer, 100) == 0 && buffer[0] == 0xa5, "FAIL cursor beyond shrink\n");
    require(file_seek(h, 6000) == 6000, "FAIL seek gap\n");
    fill(251, 19);
    require(file_write(h, buffer, 19) == 19, "FAIL gap write\n");
    require(file_seek(h, 0) == 0, "FAIL seek before append\n");
    fill(252, 13);
    require(file_append(h, buffer, 13) == 13, "FAIL append\n");
    require(file_seek(h, 4090) == 4090, "FAIL read gap seek\n");
    require(file_read(h, buffer, 1930) == 1930, "FAIL read gap\n");
    for (unsigned i = 0; i < 1930; i++) {
        unsigned pos = 4090 + i;
        unsigned char expected = pos < 4092 ? pattern(250, pos) :
                                 pos < 6000 ? 0 :
                                 pos < 6019 ? pattern(251, pos - 6000) : pattern(252, 0);
        require(buffer[i] == expected, "FAIL gap zero bytes\n");
    }
    require(file_truncate(h, 8190) == 0, "FAIL grow\n");
    require(file_truncate(h, 8184) == 0, "FAIL exact second boundary\n");
    require(file_truncate(h, 8190) == 0, "FAIL grow partial\n");
    require(file_truncate(h, 0) == 0, "FAIL truncate zero\n");
    require(file_read(h, buffer, 1) == 0, "FAIL zero cursor\n");
    require(file_truncate(h, 4092) == 0, "FAIL zero grow boundary\n");
    require(file_seek(h, 5000) == 5000, "FAIL seek after truncate\n");
    fill(253, 37);
    require(file_write(h, buffer, 37) == 37, "FAIL write after grow\n");
    require(file_seek(h, 3) == 3, "FAIL seek before append second\n");
    fill(254, 11);
    require(file_append(h, buffer, 11) == 11, "FAIL append after truncate\n");
    require(file_read(h, buffer, 1) == 0, "FAIL append cursor\n");
    require(file_truncate(h, 8190) == 0, "FAIL final grow\n");
    require(file_seek(h, FS_BYTES) == FS_BYTES, "FAIL max seek\n");
    require(file_write(h, buffer, 1) == F_FULL, "FAIL max write bound\n");
    require(file_seek(h, FS_BYTES + 1) == F_ARG, "FAIL seek bound\n");
    close_checked(h);
    verify_pattern("edge", 8190, 0, 1);
    say("fstest: seek append truncate zero gaps PASS\n");
}
static void boundary_names(unsigned long end)
{
    volatile unsigned char *p = (void *)(end - 2);
    unsigned char saved[3];
    for (unsigned i = 0; i < 3; i++) {
        saved[i] = p[i];
    }
    p[0] = 'x';
    p[1] = 0;
    long legal = file_open((const char *)p, FS_EXISTING);
    long closed = legal >= 4 ? file_close(legal) : F_HANDLE;
    p[1] = 'x';
    p[2] = 0;
    long existing = file_open((const char *)(p + 1), FS_EXISTING);
    long replace = file_open((const char *)(p + 1), FS_REPLACE);
    long remove = file_remove((const char *)(p + 1));
    for (unsigned i = 0; i < 3; i++) {
        p[i] = saved[i];
    }
    require(legal >= 4 && closed == 0, "FAIL legal end name\n");
    require(existing == F_ARG && replace == F_ARG && remove == F_ARG, "FAIL crossing whole name\n");
}
static void bad_arguments(void)
{
    require(file_open("missing", FS_EXISTING) == F_MISSING, "FAIL missing\n");
    require(file_open("missing", FS_RW) == F_MISSING, "FAIL RW creates\n");
    require(file_open("", FS_REPLACE) == F_ARG, "FAIL empty name\n");
    require(file_open("bad/name", FS_REPLACE) == F_ARG, "FAIL slash\n");
    require(file_open("12345678901234567890123456789012", FS_REPLACE) == F_ARG, "FAIL name bound\n");
    require(file_open((const char *)0, FS_REPLACE) == F_ARG, "FAIL null name\n");
    require(file_open((const char *)~0UL, FS_REPLACE) == F_ARG, "FAIL wrap name\n");
    create_pattern("x", 513, 247);
    boundary_names(USER_DATA_END);
    boundary_names(DATA_BASE + DATA_SIZE);
    boundary_names(STACK_BASE + STACK_SIZE);
    verify_pattern("x", 513, 247, 0);
    require(file_remove("x") == 0, "FAIL x cleanup\n");
    long hs[4];
    for (unsigned i = 0; i < 4; i++) {
        char name[8];
        name_for(name, i);
        hs[i] = file_open(name, FS_RW);
        require(hs[i] >= 4, "FAIL handle admit\n");
    }
    require(file_open("f004", FS_RW) == F_FULL, "FAIL handle full\n");
    require(file_open("f000", FS_REPLACE) == F_BUSY, "FAIL open conflict\n");
    require(file_remove("f000") == F_BUSY, "FAIL remove conflict\n");
    require(file_defrag() == F_BUSY, "FAIL defrag conflict\n");
    require(file_read(hs[0], (void *)0, 1) == F_ARG, "FAIL read pointer\n");
    require(file_write(hs[0], (void *)~0UL, 1) == F_ARG, "FAIL write pointer\n");
    require(file_append(hs[0], buffer, 4097) == F_ARG, "FAIL append count\n");
    require(file_read(hs[0], (void *)(USER_DATA_END - 1), 2) == F_ARG, "FAIL whole data\n");
    require(file_write(hs[0], buffer, 4097) == F_ARG, "FAIL write count\n");
    for (unsigned i = 0; i < 4; i++) {
        close_checked(hs[i]);
    }
    long h = file_open("f000", FS_RW);
    require(h >= 4 && h != hs[0], "FAIL handle generation\n");
    require(file_read(hs[0], buffer, 1) == F_HANDLE, "FAIL stale read\n");
    require(syscall3(FS_CLOSE, h, 0, 1) == F_ARG, "FAIL close reserved\n");
    require(syscall3(FS_FLUSH, h, 1, 0) == F_ARG, "FAIL flush reserved\n");
    require(syscall3(FS_SEEK, h, 0, 1) == F_ARG, "FAIL seek reserved\n");
    require(syscall3(FS_TRUNCATE, h, 0, 1) == F_ARG, "FAIL trunc reserved\n");
    close_checked(h);
    require(syscall3(FS_OPEN, (unsigned long)"f000", FS_REPLACE, 1) == F_ARG, "FAIL open reserved\n");
    require(syscall3(FS_REMOVE, (unsigned long)"f000", 0, 1) == F_ARG, "FAIL remove reserved\n");
    require(syscall3(FS_REMOVE, (unsigned long)"f000", 2, 0) == F_ARG, "FAIL remove mode reuse\n");
    require(syscall3(FS_INFO, 0, 0, 1) == F_ARG, "FAIL info reserved\n");
    require(syscall3(FS_DEFRAG, 0, 1, 0) == F_ARG, "FAIL defrag reserved\n");
    struct ListCursor c = {0, 0};
    require(file_list_page(listing, 17, &c) == F_ARG, "FAIL page capacity\n");
    require(file_list_page((void *)(USER_DATA_END - 35), 1, &c) == F_ARG, "FAIL whole page\n");
    require(file_list_page(listing, 1, (void *)(USER_DATA_END - 7)) == F_ARG, "FAIL whole cursor\n");
    require(file_list_page(listing, 1, (void *)listing) == F_ARG, "FAIL overlapping cursor\n");
    c.index = 513;
    require(file_list_page(listing, 1, &c) == F_ARG, "FAIL cursor bound\n");
    c.index = 0;
    require(file_list_page(listing, 1, &c) == 1, "FAIL first page\n");
    h = file_open("f000", FS_RW);
    require(h >= 4 && file_truncate(h, 8200) == 0, "FAIL cursor mutation\n");
    close_checked(h);
    require(file_list_page(listing, 1, &c) == F_ARG, "FAIL stale enumeration\n");
    /* Byte-aligned user ABI: listing/cursor copy must not assume C alignment. */
    for (unsigned i = 0; i < 8; i++) {
        buffer[101 + i] = 0;
    }
    require(file_list_page((void *)(buffer + 1), 1, (void *)(buffer + 101)) == 1,
            "FAIL unaligned listing/cursor\n");
    require(buffer[1] == 'e' || buffer[1] == 'f', "FAIL unaligned listing bytes\n");
    require(buffer[105] == 1, "FAIL unaligned cursor advance\n");
    h = file_open("f000", FS_RW);
    require(h >= 4 && file_seek(h, 9000) == 9000, "FAIL zero seek\n");
    require(file_write(h, buffer, 0) == 0 && file_append(h, buffer, 0) == 0, "FAIL zero write\n");
    require(file_read(h, buffer, 1) == 0, "FAIL zero write cursor\n");
    close_checked(h);
    create_pattern("1234567890123456789012345678901", 0, 0);
    verify_pattern("1234567890123456789012345678901", 0, 0, 0);
    require(file_remove("1234567890123456789012345678901") == 0, "FAIL name31 cleanup\n");
    say("fstest: owner names buffers handles reserved args PASS\n");
}
void file_test(int verify)
{
    if (!verify || verify == 2) {
        for (unsigned i = 0; i < 224; i++) {
            unsigned index = i < 80 ? i : i < 160 ? 239 - i : 160 + ((i - 160) * 17 % 64);
            char name[8];
            name_for(name, index);
            create_pattern(name, 8200 + index * 3, index);
        }
        say("fstest: ascending descending permuted inserts PASS\n");
        bad_arguments();
        edge_operations();
        create_pattern("max", 65536, 249);
        if (verify == 2) {
            say("fstest: create stage PASS\n");
            return;
        }
    }
    if (!verify || verify == 3) {
        for (unsigned i = 0; i < 224; i++) {
            if (i % 5 == 2) {
                char name[8];
                name_for(name, i);
                require(file_remove(name) == 0, "FAIL remove\n");
                require(file_remove(name) == F_MISSING, "FAIL removed status\n");
            }
        }
        say("fstest: deleted middle data blocks PASS\n");
        if (verify == 3) {
            return;
        }
    }
    if (!verify || verify == 4) {
        for (unsigned i = 2; i < 224; i += 10) {
            char name[8];
            name_for(name, i);
            create_pattern(name, final_size(i), i);
        }
        say("fstest: reclaimed allocation PASS\n");
    }
    for (unsigned i = 0; i < 224; i++) {
        char name[8];
        name_for(name, i);
        if (retained(i)) {
            verify_pattern(name, final_size(i), i, 0);
        } else {
            require(file_open(name, FS_EXISTING) == F_MISSING, "FAIL deleted cold lookup\n");
        }
    }
    verify_pattern("edge", 8190, 0, 1);
    verify_pattern("max", 65536, 249, 0);
    page_check();
    say("fsverify: persisted binary chains and exact EOF PASS\n");
}
/* Run on a fresh separate fixture. Both directory and payload exhaustion are
   exercised through U ecalls, with preflight nonmutation assertions. */
void file_pressure(void)
{
    for (unsigned i = 0; i < FS_FILES; i++) {
        char name[8];
        name_for(name, i);
        create_pattern(name, 0, 0);
    }
    require(file_open("overflow", FS_REPLACE) == F_FULL, "FAIL file limit\n");
    require(file_open("overflow", FS_EXISTING) == F_MISSING, "FAIL full create mutation\n");
    for (unsigned i = 0; i < 60; i++) {
        char name[8];
        name_for(name, i);
        long h = file_open(name, FS_RW);
        require(h >= 4 && file_truncate(h, 65536) == 0, "FAIL allocate pressure\n");
        close_checked(h);
    }
    long h = file_open("f060", FS_RW);
    require(h >= 4 && file_truncate(h, 4 * 4092) == 0, "FAIL fill last blocks\n");
    require(file_truncate(h, 4 * 4092 + 1) == F_FULL, "FAIL truncate capacity\n");
    require(file_seek(h, 4 * 4092) == 4 * 4092, "FAIL full seek\n");
    fill(246, 1);
    require(file_write(h, buffer, 1) == F_FULL, "FAIL capacity write\n");
    require(file_read(h, buffer, 1) == 0, "FAIL full size/cursor changed\n");
    close_checked(h);
    h = file_open("f061", FS_RW);
    require(h >= 4 && file_append(h, buffer, 1) == F_FULL, "FAIL capacity append\n");
    close_checked(h);
    require(file_remove("f030") == 0, "FAIL release pressure\n");
    create_pattern("f030", 65536, 245);
    verify_pattern("f030", 65536, 245, 0);
    say("fspressure: 512 files 1024 blocks preflight reuse PASS\n");
}

static void node_name(char *name, unsigned round, unsigned index)
{
    name[0] = 'n';
    name[1] = '0' + round / 100;
    name[2] = '0' + round / 10 % 10;
    name[3] = '0' + round % 10;
    name[4] = '0' + index / 10;
    name[5] = '0' + index % 10;
    name[6] = 0;
}
void file_node_pressure(void)
{
    for (unsigned round = 0; round < 256; round++) {
        for (unsigned index = 0; index < 16; index++) {
            char name[8];
            node_name(name, round, index);
            long h = file_open(name, FS_REPLACE);
            if (h == F_FULL) {
                require(file_open(name, FS_EXISTING) == F_MISSING, "FAIL node capacity mutated\n");
                require(file_open(name, FS_REPLACE) == F_FULL, "FAIL node capacity unstable\n");
                /* Distinct name that fits a retained empty leaf proves a full
                   node pool does not make every non-splitting insert fail. */
                h = file_open("a", FS_REPLACE);
                require(h >= 4, "FAIL retained leaf reuse\n");
                close_checked(h);
                require(file_remove("a") == 0, "FAIL retained leaf cleanup\n");
                for (unsigned j = 0; j < index; j++) {
                    node_name(name, round, j);
                    h = file_open(name, FS_EXISTING);
                    require(h >= 4 && file_read(h, buffer, 1) == 0, "FAIL node full old lookup\n");
                    close_checked(h);
                }
                char message[] = "fsnodes: stop 000 00 PASS\n";
                message[14] = '0' + round / 100;
                message[15] = '0' + round / 10 % 10;
                message[16] = '0' + round % 10;
                message[18] = '0' + index / 10;
                message[19] = '0' + index % 10;
                say(message);
                return;
            }
            require(h >= 4, "FAIL node pressure create\n");
            close_checked(h);
        }
        for (unsigned index = 0; index < 16; index++) {
            char name[8];
            node_name(name, round, index);
            require(file_remove(name) == 0, "FAIL node pressure delete\n");
        }
    }
    require(0, "FAIL node exhaustion not reached\n");
}
