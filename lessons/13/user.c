#include "syscall.h"
#define LINE 96
#define HISTORY 4
static char history[HISTORY][LINE];
static int history_count;
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
    say("\r\033[2K13> ");
    say(line);
    for (int i = cursor; line[i]; i++) {
        say("\033[D");
    }
}
static void read_line(char *line)
{
    static int previous_cr;
    char draft[LINE];
    int used = 0;
    int cursor = 0;
    int recalled = history_count;
    int escape = 0;
    int delete_sequence = 0;
    line[0] = 0;
    draft[0] = 0;
    say("13> ");
    for (;;) {
        int c = syscall2(SYS_READ, 0, 0);
        if (previous_cr && c == '\n') {
            previous_cr = 0;
            continue;
        }
        previous_cr = 0;
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
            previous_cr = c == '\r';
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
        const char *name = line[0] == '.' ? line + 2 : arg;
        result("exec", 0, syscall2(SYS_EXEC, (unsigned long)name, 0));
    } else if (equal(line, "help")) {
        say("help echo ps/jobs run spin|sleep|exit [arg] kill pid wait pid sleep ticks stats shutdown\n");
        say("ls fwrite NAME TEXT cat/fread NAME rm NAME fsinfo fappend NAME TEXT\n");
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
    require(syscall2(SYS_WRITE, 0x80500000, 1) == E_ARG, "FAIL worker app pointer\n");
    require(syscall2(SYS_EXEC, 0, 0) == E_OWNER, "FAIL exec owner before pointer\n");
    require(syscall2(FS_OPEN, 0, FS_REPLACE) == E_OWNER, "FAIL file owner before pointer\n");
    require(syscall2(FS_INFO, 0, 0) == E_OWNER, "FAIL file owner diagnostic\n");
    user_exit(argument);
}
