#include "syscall.h"
#define LINE 96
#define HISTORY 4
static char history[HISTORY][LINE];
static int history_count;
static int previous_cr;
static unsigned long command_drop_baseline;
static unsigned char paste[8192 + 33] __attribute__((section(".paste")));

/* One CRLF state is shared by command editor and raw body reader. */
static int input_byte(void)
{
    for (;;) {
        int byte = syscall2(SYS_READ, 0, 0);
        if (previous_cr && byte == '\n') {
            previous_cr = 0;
            continue;
        }
        previous_cr = byte == '\r';
        return byte == '\r' ? '\n' : byte;
    }
}
static const char *commands[] = {
    "help", "echo", "ps", "jobs", "run", "kill", "wait", "sleep", "stats", "shutdown", "ls", "fwrite", "cat", "rm", "fsinfo", "fstest", "fsverify", "fappend", "fseek", "ftruncate", "fread", "defrag", "fspressure", "fsnodes", "exec"
};
static int length(const char *s)
{
    int n = 0;
    while (s[n]) {
        n++;
    }
    return n;
}
static int equal(const char *a, const char *b)
{
    while (*a && *a == *b) {
        a++;
        b++;
    }
    return *a == *b;
}
static void copy(char *to, const char *from)
{
    while ((*to++ = *from++) != 0) {
    }
}
static char *decimal(char *out, long value)
{
    char reversed[24];
    unsigned long magnitude = value < 0 ? (unsigned long)-value : (unsigned long)value;
    int used = 0;
    if (value < 0) {
        *out++ = '-';
    }
    do {
        reversed[used++] = '0' + magnitude % 10;
        magnitude /= 10;
    } while (magnitude);
    while (used > 0) {
        *out++ = reversed[--used];
    }
    return out;
}
static long parse(const char *s)
{
    if (!*s) {
        return -1;
    }
    long value = 0;
    while (*s) {
        if (*s < '0' || *s > '9' || value > 100000000) {
            return -1;
        }
        value = value * 10 + *s++ - '0';
    }
    return value;
}
static void redraw(char *line, int cursor)
{
    say("\r\033[2K14> ");
    say(line);
    for (int i = cursor; line[i]; i++) {
        say("\033[D");
    }
}
static void read_line(char *line)
{

    char draft[LINE];
    int used = 0;
    int cursor = 0;
    int recalled = history_count;
    int escape = 0;
    int delete_sequence = 0;
    line[0] = 0;
    draft[0] = 0;
    /* Boot's zero-loss baseline covers bytes already queued BEFORE this
     * command, not just drops occurring after raw mode is entered. */
    say("14> ");
    for (;;) {
        int c = input_byte();
        if (escape == 1) {
            escape = c == '[' ? 2 : 0;
            continue;
        }
        if (escape == 2) {
            escape = 0;
            if (c == '3') {
                delete_sequence = 1;
                continue;
            }
            if (c == 'D' && cursor > 0) {
                cursor--;
            } else if (c == 'C' && cursor < used) {
                cursor++;
            } else if (c == 'A' && recalled > 0) {
                if (recalled == history_count) {
                    copy(draft, line);
                }
                copy(line, history[--recalled]);
                cursor = used = length(line);
            } else if (c == 'B' && recalled < history_count) {
                recalled++;
                copy(line, recalled == history_count ? draft : history[recalled]);
                cursor = used = length(line);
            }
            redraw(line, cursor);
            continue;
        }
        if (delete_sequence) {
            delete_sequence = 0;
            if (c == '~' && cursor < used) {
                for (int i = cursor; i < used; i++) {
                    line[i] = line[i + 1];
                }
                used--;
                redraw(line, cursor);
            }
            continue;
        }
        if (c == 27) {
            escape = 1;
            continue;
        }
        if (c == '\r' || c == '\n') {
            say("\n");
            if (used) {
                if (history_count == HISTORY) {
                    for (int i = 1; i < HISTORY; i++) {
                        copy(history[i - 1], history[i]);
                    }
                    history_count--;
                }
                copy(history[history_count++], line);
            }
            return;
        }
        if (c == 8 || c == 127) {
            if (cursor > 0) {
                cursor--;
                for (int i = cursor; i < used; i++) {
                    line[i] = line[i + 1];
                }
                used--;
            }
        } else if (c == '\t') {
            int matches = 0;
            const char *match = 0;
            for (int n = 0; n < (int)(sizeof(commands) / sizeof(commands[0])); n++) {
                int i = 0;
                while (i < used && commands[n][i] == line[i]) {
                    i++;
                }
                if (i == used) {
                    matches++;
                    match = commands[n];
                }
            }
            if (matches == 1) {
                copy(line, match);
                cursor = used = length(line);
            }
        } else if (c >= 32 && c <= 126 && used < LINE - 1) {
            for (int i = used; i >= cursor; i--) {
                line[i + 1] = line[i];
            }
            line[cursor++] = c;
            used++;
        }
        redraw(line, cursor);
    }
}
static void result(const char *label, long target, long value)
{
    /* One WRITE is one locked record. Multiple say/ecall fragments can be
       interleaved by another hart's zombie/audit line even with a UART lock. */
    char text[96];
    copy(text, label);
    char *out = text + length(text);
    copy(out, " target=");
    out = decimal(out + 8, target);
    copy(out, " result=");
    out = decimal(out + 8, value);
    *out++ = '\n';
    *out = 0;
    say(text);
}
static void text_line(const char *prefix, const char *value)
{
    char text[128];
    copy(text, prefix);
    int used = length(text);
    copy(text + used, value);
    used += length(value);
    text[used++] = '\n';
    text[used] = 0;
    say(text);
}
static void raw_append(const char *name, const char *delimiter)
{
    unsigned delimiter_size = length(delimiter);
    if (!delimiter_size || delimiter_size > 31) {
        say("raw: invalid delimiter\n");
        return;
    }
    for (unsigned index = 0; index < delimiter_size; index++) {
        if (delimiter[index] < 33 || delimiter[index] > 126) {
            say("raw: invalid delimiter\n");
            return;
        }
    }
    unsigned used = 0;
    unsigned line_start = 0;
    unsigned line_size = 0;
    int matches = 1;
    int rejected = 0;
    say("raw: collecting (terminator required even after cancellation)\n");
    for (;;) {
        int byte = input_byte();
        if (byte == '\n') {
            if (matches && line_size == delimiter_size) {
                used = line_start;
                break;
            }
            if (used < sizeof(paste)) {
                paste[used++] = '\n';
            } else {
                rejected = 1;
            }
            if (used > 8192) {
                rejected = 1;
            }
            line_start = used;
            line_size = 0;
            matches = 1;
            continue;
        }
        if ((byte < 32 && byte != '\t') || byte == 127) {
            rejected = 1;
        }
        if (line_size >= delimiter_size || byte != (unsigned char)delimiter[line_size]) {
            matches = 0;
        }
        if (line_size < 32) {
            line_size++;
        }
        if (used < sizeof(paste)) {
            paste[used++] = byte;
        } else {
            rejected = 1;
        }
    }
    if ((unsigned long)syscall2(SYS_RX_DROPS, 0, 0) != command_drop_baseline) {
        rejected = 1;
    }
    if (rejected) {
        say("raw: rejected; drained; unchanged\n");
        return;
    }
    long value = used ? syscall3(SYS_APPEND_FILE, (unsigned long)name, (unsigned long)paste, used) : 0;
    result("raw", 0, value);
}
static void execute(char *line)
{
    char *arg = line;
    while (*arg && *arg != ' ') {
        arg++;
    }
    if (*arg) {
        *arg++ = 0;
    }
    while (*arg == ' ') {
        arg++;
    }
    if (!*line) {
        return;
    }
    if (equal(line, "exec") || (line[0] == '.' && line[1] == '/')) {
        char *arguments[5] = {0};
        char *next = line[0] == '.' ? line + 2 : arg;
        unsigned count = 0;
        if (line[0] == '.') {
            arguments[count++] = next;
            next = arg;
        }
        while (*next && count < 4) {
            arguments[count++] = next;
            while (*next && *next != ' ') {
                next++;
            }
            if (*next) {
                *next++ = 0;
            }
            while (*next == ' ') {
                next++;
            }
        }
        long value = E_ARG;
        if (count && !*next) {
            value = count == 1 ? syscall2(SYS_EXEC, (unsigned long)arguments[0], 0) :
                    syscall3(SYS_EXEC, (unsigned long)arguments[0], count, (unsigned long)arguments);
        }
        result("exec", 0, value);
    } else if (equal(line, "abitest")) {
        char overlong[49];
        for (unsigned index = 0; index < 48; index++) {
            overlong[index] = 'a';
        }
        overlong[48] = 0;
        const char *vector[5] = {"cc", "a.c", "out", 0, 0};
        require(syscall3(SYS_EXEC, (unsigned long)"cc", 5, (unsigned long)vector) == E_ARG, "FAIL argc bound\n");
        require(syscall3(SYS_EXEC, (unsigned long)"cc", 0, (unsigned long)vector) == E_ARG, "FAIL zero argv reserved\n");
        require(syscall3(SYS_EXEC, (unsigned long)"cc", 1, (unsigned long)vector + 1) == E_ARG, "FAIL argv alignment\n");
        require(syscall3(SYS_EXEC, (unsigned long)"cc", 1, USER_DATA_END - 8) == E_ARG, "FAIL argv crossing interval\n");
        require(syscall3(SYS_EXEC, (unsigned long)"cc", 1, STACK_BASE + STACK_SIZE) == E_ARG, "FAIL argv other stack\n");
        require(syscall3(SYS_EXEC, (unsigned long)"cc", 1, (unsigned long)vector) == E_ARG, "FAIL argv terminator\n");
        vector[0] = overlong;
        vector[1] = 0;
        require(syscall3(SYS_EXEC, (unsigned long)"cc", 1, (unsigned long)vector) == E_ARG, "FAIL arg length\n");
        vector[0] = (const char *)(USER_DATA_END - 1);
        /* Reject an interval crossing vector before touching any contents. */
        require(syscall3(SYS_EXEC, (unsigned long)"cc", 4, (unsigned long)vector) == E_ARG, "FAIL malformed vector\n");
        vector[0] = "";
        require(syscall3(SYS_EXEC, (unsigned long)"cc", 1, (unsigned long)vector) == E_ARG, "FAIL empty argument\n");
        vector[0] = (const char *)(STACK_BASE + STACK_SIZE);
        require(syscall3(SYS_EXEC, (unsigned long)"cc", 1, (unsigned long)vector) == E_ARG, "FAIL other-stack argument\n");
        *(char *)(PASTE_BASE + PASTE_SIZE - 1) = 'x';
        vector[0] = (const char *)(PASTE_BASE + PASTE_SIZE - 1);
        require(syscall3(SYS_EXEC, (unsigned long)"cc", 1, (unsigned long)vector) == E_ARG, "FAIL NUL prefix crossing interval\n");
        require(syscall3(SYS_STORE, 0, 0, 0) == E_OWNER, "FAIL shell STORE ownership\n");
        say("PASS shell argv admission, no partial publication\n");
    } else if (equal(line, "help")) {
        say("help echo ps/jobs run spin|sleep|exit [arg] kill pid wait pid sleep ticks stats shutdown\n");
        say("exec NAME or ./NAME loads an ordinary-file RVEXEC1 application\n");
        say("ls fwrite NAME TEXT cat/fread NAME rm NAME fsinfo fappend NAME TEXT\n");
        say("fappend NAME <<END collects raw bytes; terminator required even after Ctrl-C/D\n");
        say("fseek NAME OFFSET [TEXT] ftruncate NAME SIZE defrag\n");
        say("fstest [create|delete|recreate] fsverify fspressure fsnodes (fresh test disks only)\n");
    } else if (equal(line, "ls")) {
        struct FileEntry entries[7];
        struct ListCursor cursor = {0, 0};
        for (;;) {
            long count = file_list_page(entries, 7, &cursor);
            if (count < 0) {
                result("ls", 0, count);
                break;
            }
            if (!count) {
                break;
            }
            for (long i = 0; i < count; i++) {
                char text[96];
                copy(text, "file: ");
                copy(text + 6, entries[i].name);
                char *end = text + length(text);
                copy(end, " size=");
                end = decimal(end + 6, entries[i].size);
                *end++ = '\n';
                *end = 0;
                say(text);
            }
        }
    } else if (equal(line, "fsinfo")) {
        syscall2(FS_INFO, 0, 0);
    } else if (equal(line, "fstest") || equal(line, "fsverify")) {
        int phase = equal(line, "fsverify") ? 1 :
                    equal(arg, "create") ? 2 : equal(arg, "delete") ? 3 :
                    equal(arg, "recreate") ? 4 : equal(arg, "epoch-write") ? 5 :
                    equal(arg, "epoch-append") ? 6 : equal(arg, "epoch-poison") ? 7 :
                    equal(arg, "replay") ? 8 : 0;
        file_test(phase);
    } else if (equal(line, "rm")) {
        result("rm", 0, file_remove(arg));
    } else if (equal(line, "defrag")) {
        result("defrag", 0, file_defrag());
    } else if (equal(line, "fsnodes")) {
        file_node_pressure();
    } else if (equal(line, "fspressure")) {
        file_pressure();
    } else if (equal(line, "fseek") || equal(line, "ftruncate")) {
        char *number = arg;
        while (*number && *number != ' ') {
            number++;
        }
        if (*number) {
            *number++ = 0;
        }
        char *text = number;
        while (*text && *text != ' ') {
            text++;
        }
        int has_text = *text != 0;
        if (*text) {
            *text++ = 0;
        }
        long value = parse(number);
        long h = value >= 0 ? file_open(arg, FS_RW) : F_ARG;
        if (h >= 0) {
            value = equal(line, "ftruncate") ? file_truncate(h, value) : file_seek(h, value);
            if (value >= 0 && has_text && equal(line, "fseek")) {
                value = file_write(h, text, length(text));
            }
            long closed = file_close(h);
            if (closed < 0) {
                value = closed;
            }
        } else {
            value = h;
        }
        result(line, 0, value);
    } else if (equal(line, "fwrite") || equal(line, "fappend")) {
        char *text = arg;
        while (*text && *text != ' ') {
            text++;
        }
        if (*text) {
            *text++ = 0;
        }
        if (equal(line, "fappend") && text[0] == '<' && text[1] == '<') {
            raw_append(arg, text + 2);
            return;
        }
        long h = file_open(arg, equal(line, "fappend") ? FS_RW : FS_REPLACE);
        long value = h;
        if (h >= 0) {
            value = equal(line, "fappend") ? file_append(h, text, length(text)) :
                    file_write(h, text, length(text));
            long closed = file_close(h);
            if (closed < 0) {
                value = closed;
            }
        }
        result(line, 0, value);
    } else if (equal(line, "cat") || equal(line, "fread")) {
        long h = file_open(arg, FS_EXISTING);
        long value = h;
        if (h >= 0) {
            char bytes[256];
            for (;;) {
                value = file_read(h, bytes, sizeof(bytes));
                if (value <= 0) {
                    break;
                }
                syscall2(SYS_WRITE, (unsigned long)bytes, value);
            }
            say("\n");
            long closed = file_close(h);
            if (closed < 0) {
                value = closed;
            }
        }
        result("cat", 0, value);
    } else if (equal(line, "echo")) {
        text_line("echo: ", arg);
    } else if (equal(line, "ps") || equal(line, "jobs")) {
        syscall2(SYS_PS, 0, 0);
    } else if (equal(line, "stats")) {
        syscall2(SYS_STATS, 0, 0);
    } else if (equal(line, "shutdown")) {
        syscall2(SYS_DONE, 0, 0);
    } else if (equal(line, "run")) {
        char *value = arg;
        while (*value && *value != ' ') {
            value++;
        }
        if (*value) {
            *value++ = 0;
        }
        long entry = equal(arg, "spin") ? WORK_SPIN :
                     equal(arg, "sleep") ? WORK_SLEEP :
                     equal(arg, "exit") ? WORK_EXIT : 0;
        long parameter = *value ? parse(value) : (entry == WORK_SLEEP ? 10 : 0);
        long pid = entry && parameter >= (entry == WORK_SLEEP ? 1 : 0) &&
                   parameter <= (entry == WORK_SLEEP ? 1000 : 255)
                   ? spawn(entry, parameter) : E_ARG;
        result("run", entry, pid);
    } else if (equal(line, "wait") || equal(line, "kill")) {
        long pid = parse(arg);
        long value = equal(line, "wait") ? wait_child(pid) : kill_child(pid);
        result(line, pid, value);
    } else if (equal(line, "sleep")) {
        long ticks = parse(arg);
        result("sleep", ticks, sleep_ticks(ticks));
    } else {
        text_line("unknown: ", line);
    }
}
void user_main(void)
{
    char line[LINE];
    say("shell: U-mode builtins from disk; help for commands\n");
    for (;;) {
        read_line(line);
        execute(line);
    }
}
void worker_main(long entry, long argument, volatile struct UserData *data)
{
    if (entry == WORK_SLEEP) {
        data->counter++;
        sleep_ticks(argument);
        user_exit(23);
    }
    require(syscall2(SYS_READFILE, 0, 0) == E_OWNER, "FAIL snapshot owner before pointer\n");
    require(syscall3(SYS_STORE, 0, 0, 0) == E_OWNER, "FAIL store owner before pointer\n");
    require(syscall2(SYS_WRITE, 0x80500000, 1) == E_ARG, "FAIL worker app pointer\n");
    require(syscall2(SYS_EXEC, 0, 0) == E_OWNER, "FAIL exec owner before pointer\n");
    require(syscall2(FS_OPEN, 0, FS_REPLACE) == E_OWNER, "FAIL file owner before pointer\n");
    require(syscall2(FS_INFO, 0, 0) == E_OWNER, "FAIL file owner diagnostic\n");
    user_exit(argument);
}
