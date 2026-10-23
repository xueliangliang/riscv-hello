#include "syscall.h"
static unsigned char output[4096];
static unsigned char input[4096];
static const char *names[] = {"b511", "b512", "b513", "b1024", "b4096"};
static const unsigned sizes[] = {511, 512, 513, 1024, 4096};
static long open_file(const char *name, unsigned mode)
{
    return file_open(name, mode);
}
static void checked_close(long h)
{
    require(file_close(h) == 0, "FAIL close\n");
}
static void create(const char *name, unsigned count)
{
    long h = open_file(name, FS_REPLACE);
    require(h >= 4, "FAIL create\n");
    require(file_write(h, output, count) == count, "FAIL write\n");
    require(file_flush(h) == 0, "FAIL flush\n");
    checked_close(h);
    require(file_close(h) == F_HANDLE, "FAIL stale close\n");
}
static void verify(const char *name, unsigned count)
{
    long h = open_file(name, FS_EXISTING);
    require(h >= 4, "FAIL open existing\n");
    unsigned offset = 0;
    /* Unaligned, repeated reads must maintain an independent logical cursor. */
    while (offset < count) {
        unsigned chunk = count - offset;
        if (chunk > 257) {
            chunk = 257;
        }
        require(file_read(h, input, chunk) == chunk, "FAIL read length\n");
        for (unsigned j = 0; j < chunk; j++) {
            require(input[j] == output[offset + j], "FAIL exact content\n");
        }
        offset += chunk;
    }
    input[0] = 0xa5;
    require(syscall3(FS_READ, h, (unsigned long)input, 1) == 0, "FAIL EOF\n");
    require(input[0] == 0xa5, "FAIL EOF touched bytes\n");
    require(syscall3(FS_WRITE, h, (unsigned long)output, 1) == F_MODE, "FAIL readonly handle\n");
    checked_close(h);
}
static void boundary_names(unsigned long end)
{
    /* Flat physical U access lets this probe stage both sides. Restore every
       boundary byte before asserting, including the adjacent private block. */
    volatile unsigned char *edge = (void *)(end - 2);
    unsigned char saved[3];
    for (unsigned i = 0; i < 3; i++) {
        saved[i] = edge[i];
    }
    edge[0] = 'x';
    edge[1] = 0;
    long legal = open_file((const char *)edge, FS_EXISTING);
    long closed = legal >= 4 ? file_close(legal) : F_HANDLE;
    edge[1] = 'x';
    edge[2] = 0;
    long existing = open_file((const char *)(edge + 1), FS_EXISTING);
    long replace = open_file((const char *)(edge + 1), FS_REPLACE);
    long remove = file_remove((const char *)(edge + 1));
    for (unsigned i = 0; i < 3; i++) {
        edge[i] = saved[i];
    }
    require(legal >= 4, "FAIL legal name boundary\n");
    require(closed == 0, "FAIL boundary close\n");
    require(existing == F_ARG, "FAIL crossing existing name\n");
    require(replace == F_ARG, "FAIL crossing replace name\n");
    require(remove == F_ARG, "FAIL crossing remove name\n");
    verify("x", 513);
}
static void name_arguments(void)
{
    /* Rejected open/remove must neither truncate nor delete the raw-checked
       b511 fixture. FS_REMOVE has a reserved zero argument, not an open mode. */
    require(open_file("b511", 2) == F_ARG, "FAIL invalid replace mode\n");
    require(syscall2(FS_REMOVE, (unsigned long)"b511", 1) == F_ARG,
            "FAIL remove reserved argument\n");
    verify("b511", 511);
    char unterminated[32];
    for (unsigned i = 0; i < sizeof(unterminated); i++) {
        unterminated[i] = 'x';
    }
    require(open_file(unterminated, FS_REPLACE) == F_ARG, "FAIL unterminated name\n");
    /* First test creation rejection, then existing-file preservation. */
    volatile unsigned char *edge = (void *)(USER_DATA_END - 1);
    unsigned char a = edge[0];
    unsigned char b = edge[1];
    edge[0] = 'x';
    edge[1] = 0;
    long result = open_file((const char *)edge, FS_REPLACE);
    edge[0] = a;
    edge[1] = b;
    require(result == F_ARG, "FAIL crossing name creates\n");
    require(open_file("x", FS_EXISTING) == F_MISSING, "FAIL crossing directory mutation\n");
    create("x", 513);
    boundary_names(USER_DATA_END);
    boundary_names(DATA_BASE + DATA_SIZE);
    boundary_names(STACK_BASE + STACK_SIZE);
    require(file_remove("x") == 0, "FAIL boundary cleanup\n");
    say("fstest: name regions and reserved remove argument PASS\n");
}
void file_test(int checking)
{
    for (unsigned i = 0; i < 4096; i++) {
        output[i] = 33 + (i * 17 + 7) % 90;
    }
    if (!checking) {
        require(open_file("absent", FS_EXISTING) == F_MISSING, "FAIL missing creates\n");
        require(open_file("", FS_REPLACE) == F_ARG, "FAIL empty name\n");
        require(open_file("bad/name", FS_REPLACE) == F_ARG, "FAIL unsafe name\n");
        require(open_file("12345678901234567890123456789012", FS_REPLACE) == F_ARG, "FAIL long name\n");
        require(open_file("x", 2) == F_ARG, "FAIL mode\n");
        require(syscall2(FS_OPEN, 0, 0) == F_ARG, "FAIL null name\n");
        require(syscall2(FS_OPEN, ~0UL, 0) == F_ARG, "FAIL wrapped name\n");
        require(syscall3(FS_READ, 0, (unsigned long)input, 1) == F_HANDLE, "FAIL invalid handle\n");
        for (unsigned i = 0; i < 5; i++) {
            create(names[i], sizes[i]);
            verify(names[i], sizes[i]);
        }
        name_arguments();
        create("short", 513);
        create("short", 3);
        verify("short", 3);
        create("reuse", 1024);
        require(syscall2(FS_REMOVE, (unsigned long)"reuse", 0) == 0, "FAIL delete\n");
        require(open_file("reuse", FS_EXISTING) == F_MISSING, "FAIL deleted exists\n");
        create("reused", 513);
        create("1234567890123456789012345678901", 0);
        verify("1234567890123456789012345678901", 0);
        require(syscall2(FS_REMOVE, (unsigned long)"1234567890123456789012345678901", 0) == 0, "FAIL name31\n");
        long hs[4];
        for (unsigned i = 0; i < 4; i++) {
            hs[i] = open_file(names[i], FS_EXISTING);
            require(hs[i] >= 4, "FAIL handle admission\n");
        }
        require(open_file(names[4], FS_EXISTING) == F_FULL, "FAIL handle limit\n");
        require(open_file(names[0], FS_REPLACE) == F_BUSY, "FAIL replace open\n");
        require(syscall2(FS_REMOVE, (unsigned long)names[0], 0) == F_BUSY, "FAIL delete open\n");
        require(syscall3(FS_READ, hs[0], 0, 1) == F_ARG, "FAIL read pointer\n");
        require(syscall3(FS_READ, hs[0], USER_DATA_END - 1, 2) == F_ARG, "FAIL crossing pointer\n");
        require(syscall3(FS_READ, hs[0], STACK_BASE + STACK_SIZE - 1, 2) == F_ARG, "FAIL crossing stack\n");
        require(syscall3(FS_READ, hs[0], (unsigned long)input, 4097) == F_ARG, "FAIL read oversize\n");
        for (unsigned i = 0; i < 4; i++) {
            checked_close(hs[i]);
        }
        long h = open_file("short", FS_REPLACE);
        require(h >= 4 && h != hs[0], "FAIL generation reuse\n");
        require(syscall3(FS_READ, hs[0], (unsigned long)input, 1) == F_HANDLE, "FAIL stale generation\n");
        require(syscall3(FS_WRITE, h, ~0UL, 1) == F_ARG, "FAIL write pointer\n");
        require(syscall3(FS_WRITE, h, (unsigned long)output, 4097) == F_ARG, "FAIL write oversize\n");
        require(syscall3(FS_WRITE, h, (unsigned long)output, 3) == 3, "FAIL short restore\n");
        checked_close(h);
        /* Seven live files; exactly nine free directory/extents. */
        char name[] = "fill0";
        for (unsigned i = 0; i < 9; i++) {
            name[4] = '0' + i;
            create(name, 0);
        }
        require(open_file("overflow", FS_REPLACE) == F_FULL, "FAIL file capacity\n");
        require(open_file("overflow", FS_EXISTING) == F_MISSING, "FAIL capacity mutated\n");
        for (unsigned i = 0; i < 9; i++) {
            name[4] = '0' + i;
            require(syscall2(FS_REMOVE, (unsigned long)name, 0) == 0, "FAIL fill cleanup\n");
        }
        /* NUL/high-bit bytes must follow counts, not string/console semantics. */
        for (unsigned i = 0; i < 4096; i++) {
            output[i] = (i * 37 + 3) & 255;
        }
        create("binary", 4096);
        verify("binary", 4096);
        require(syscall2(FS_REMOVE, (unsigned long)"binary", 0) == 0, "FAIL binary cleanup\n");
        for (unsigned i = 0; i < 4096; i++) {
            output[i] = 33 + (i * 17 + 7) % 90;
        }
        say("fstest: exact bytes, bounds, EOF, handles, capacity PASS\n");
    }
    for (unsigned i = 0; i < 5; i++) {
        verify(names[i], sizes[i]);
    }
    verify("short", 3);
    verify("reused", 513);
    say("fsverify: persisted exact patterns PASS\n");
}
