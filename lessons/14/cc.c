#include "syscall.h"
#include "formats.h"
#include "integer-runtime.h"

/* All capacities are static workspaces, not a heap. The guest loader clears
 * these bytes and checks the linker's memory bound before publishing READY. */
#define SOURCE_LIMIT 8192
#define NODE_LIMIT 4096
#define SYMBOL_LIMIT 256
#define CODE_LIMIT 32768
#define STRING_LIMIT 8192
#define DEPTH_LIMIT 64

enum TokenKind {
    T_END = 256, T_NAME, T_NUMBER, T_STRING, T_EQ, T_NE, T_LE, T_GE
};
enum NodeKind {
    N_LITERAL = 300, N_LOCAL, N_STORE, N_POSITIVE, N_NEGATE, N_NOT,
    N_BLOCK, N_IF, N_WHILE, N_RETURN, N_PUTS, N_PRINT, N_EMPTY
};
struct Node {
    int kind;
    int left;
    int right;
    int third;
    int next;
    unsigned line;
    unsigned long value;
};
struct Symbol {
    char name[32];
    unsigned scope;
    unsigned slot;
    unsigned initializing;
};
static char source[SOURCE_LIMIT + 1];
static struct Node nodes[NODE_LIMIT];
static struct Symbol symbols[SYMBOL_LIMIT];
static unsigned char strings[STRING_LIMIT];
static unsigned char image[65536];
static unsigned source_size;
static unsigned position;
static unsigned line_number = 1;
static unsigned token_line;
static int token;
static char token_name[32];
static unsigned long token_value;
static unsigned token_string_size;
static unsigned node_count = 1;
static unsigned symbol_count;
static unsigned local_count;
static unsigned scope;
static unsigned parse_depth;
static unsigned statement_depth;
static unsigned string_size;
static unsigned code_size;
static unsigned evaluation_depth;
static unsigned maximum_evaluation_depth;
static unsigned generation_depth;
static unsigned token_count;

static int same(const char *left, const char *right)
{
    while (*left && *left == *right) {
        left++;
        right++;
    }
    return *left == *right;
}
static void print_unsigned(unsigned long value)
{
    char buffer[24];
    unsigned count = 0;
    do {
        buffer[count++] = '0' + value % 10;
        value /= 10;
    } while (value);
    while (count) {
        syscall2(SYS_WRITE, (unsigned long)&buffer[--count], 1);
    }
}
static void error(const char *message) __attribute__((noreturn));
static void error(const char *message)
{
    say("cc: line ");
    print_unsigned(token_line ? token_line : line_number);
    say(": ");
    say(message);
    say("\n");
    unsigned context = 0;
    unsigned context_line = 1;
    while (context < source_size && context_line < token_line) {
        context_line += source[context++] == '\n';
    }
    unsigned context_size = 0;
    while (context + context_size < source_size && source[context + context_size] != '\n' && context_size < 96) {
        context_size++;
    }
    say("  > ");
    syscall2(SYS_WRITE, (unsigned long)(source + context), context_size);
    say("\n");
    user_exit(1);
}
static int letter(unsigned byte)
{
    return (byte >= 'a' && byte <= 'z') || (byte >= 'A' && byte <= 'Z') || byte == '_';
}
static int digit(unsigned byte)
{
    return byte >= '0' && byte <= '9';
}
static void reject_unsupported_operator(unsigned start)
{
    /* Maximal munch applies before expression parsing. Never reinterpret ++
     * as two unary/binary + tokens. Whitespace and comments separate tokens.
     * Longest spellings precede their prefixes (including C digraphs). */
    static const char *const unsupported[] = {
        "%:%:", "<<=", ">>=", "...", "++", "--", "->", "+=", "-=", "*=",
        "/=", "%=", "<<", ">>", "&&", "||", "&=", "|=", "^=", "##",
        "<:", ":>", "<%", "%>", "%:"
    };
    for (unsigned index = 0; index < sizeof(unsupported) / sizeof(unsupported[0]); index++) {
        const char *spelling = unsupported[index];
        unsigned length = 0;
        while (spelling[length] && start + length < source_size &&
               source[start + length] == spelling[length]) {
            length++;
        }
        if (!spelling[length]) {
            char message[64];
            const char *prefix = "unsupported operator token ";
            unsigned used = 0;
            while (*prefix) {
                message[used++] = *prefix++;
            }
            for (unsigned byte = 0; byte <= length; byte++) {
                message[used + byte] = spelling[byte];
            }
            error(message);
        }
    }
}
static void lex(void)
{
    if (++token_count > 8192) {
        error("token capacity exceeded");
    }
    for (;;) {
        while (position < source_size && (source[position] == ' ' || source[position] == '\t' ||
               source[position] == '\n' || source[position] == '\r')) {
            line_number += source[position++] == '\n';
        }
        token_line = line_number;
        if (position + 1 < source_size && source[position] == '/' && source[position + 1] == '/') {
            while (position < source_size && source[position] != '\n') {
                position++;
            }
            continue;
        }
        if (position + 1 < source_size && source[position] == '/' && source[position + 1] == '*') {
            position += 2;
            while (position + 1 < source_size && !(source[position] == '*' && source[position + 1] == '/')) {
                line_number += source[position++] == '\n';
            }
            if (position + 1 >= source_size) {
                error("unterminated comment");
            }
            position += 2;
            continue;
        }
        break;
    }
    if (position == source_size) {
        token = T_END;
        return;
    }
    unsigned byte = (unsigned char)source[position++];
    if (letter(byte)) {
        unsigned used = 0;
        do {
            if (used == 31) {
                error("identifier exceeds 31 bytes");
            }
            token_name[used++] = byte;
            byte = position < source_size ? (unsigned char)source[position] : 0;
            if (!letter(byte) && !digit(byte)) {
                break;
            }
            position++;
        } while (1);
        token_name[used] = 0;
        static const char *const unsupported[] = {"char", "short", "long", "unsigned", "signed", "double", "float",
            "struct", "union", "enum", "typedef", "const", "volatile", "static", "extern", "auto",
            "register", "goto", "for", "do", "switch", "case", "default", "break", "continue", "sizeof"};
        for (unsigned index = 0; index < sizeof(unsupported) / sizeof(unsupported[0]); index++) {
            if (same(token_name, unsupported[index])) {
                error("unsupported C keyword");
            }
        }
        token = T_NAME;
        return;
    }
    if (digit(byte)) {
        token_value = byte - '0';
        while (position < source_size && digit(source[position])) {
            unsigned next = source[position++] - '0';
            if (token_value > (0x7fffffffffffffffUL - next) / 10) {
                error("integer literal overflow");
            }
            token_value = token_value * 10 + next;
        }
        token = T_NUMBER;
        return;
    }
    if (byte == '"') {
        token_value = string_size;
        token_string_size = 0;
        while (position < source_size && source[position] != '"') {
            byte = (unsigned char)source[position++];
            if (byte == '\n' || byte == '\r' || byte == 0 || byte < 32) {
                error("invalid raw byte in string");
            }
            if (byte == '\\') {
                if (position == source_size) {
                    error("unterminated string escape");
                }
                byte = (unsigned char)source[position++];
                if (byte == 'n') {
                    byte = '\n';
                } else if (byte == 'r') {
                    byte = '\r';
                } else if (byte == 't') {
                    byte = '\t';
                } else if (byte != '\\' && byte != '"') {
                    error("unsupported string escape");
                }
            }
            if (token_string_size == 1024 || string_size == STRING_LIMIT) {
                error("string capacity exceeded");
            }
            strings[string_size++] = byte;
            token_string_size++;
        }
        if (position == source_size) {
            error("unterminated string");
        }
        position++;
        token = T_STRING;
        return;
    }
    reject_unsupported_operator(position - 1);
    if ((byte == '=' || byte == '!' || byte == '<' || byte == '>') &&
        position < source_size && source[position] == '=') {
        position++;
        token = byte == '=' ? T_EQ : byte == '!' ? T_NE : byte == '<' ? T_LE : T_GE;
        return;
    }
    const char *punctuation = "+-*/%!=<>(){};,";
    for (unsigned index = 0; punctuation[index]; index++) {
        if (byte == (unsigned char)punctuation[index]) {
            token = byte;
            return;
        }
    }
    error("unsupported token");
}
static int keyword(const char *word)
{
    return token == T_NAME && same(token_name, word);
}
static void expect(int wanted)
{
    if (token != wanted) {
        error("unexpected token / missing punctuation");
    }
    lex();
}
static int node(int kind, int left, int right, int third, unsigned long value)
{
    if (node_count == NODE_LIMIT) {
        error("AST capacity exceeded");
    }
    unsigned index = node_count++;
    nodes[index].kind = kind;
    nodes[index].left = left;
    nodes[index].right = right;
    nodes[index].third = third;
    nodes[index].value = value;
    nodes[index].line = token_line;
    return index;
}
static unsigned find_local(const char *name)
{
    for (unsigned index = symbol_count; index > 0; index--) {
        if (same(symbols[index - 1].name, name)) {
            /* The new declaration already shadows an outer name, but cannot
             * read OR assign its own slot until its initializer is complete. */
            if (symbols[index - 1].initializing) {
                error("local referenced in its own initializer");
            }
            return symbols[index - 1].slot;
        }
    }
    error("unknown local or unsupported function/type");
}
static int expression(unsigned minimum);
static int primary(void)
{
    int result;
    if (++parse_depth > DEPTH_LIMIT) {
        error("expression nesting exceeded");
    }
    if (token == T_NUMBER) {
        result = node(N_LITERAL, 0, 0, 0, token_value);
        lex();
    } else if (token == '+' || token == '-' || token == '!') {
        int operation = token;
        lex();
        result = primary();
        /* Unary + preserves the value, not the operand's lvalue category.
         * Parentheses alone deliberately retain the underlying N_LOCAL. */
        int kind = operation == '+' ? N_POSITIVE : operation == '-' ? N_NEGATE : N_NOT;
        result = node(kind, result, 0, 0, 0);
    } else if (token == '(') {
        lex();
        result = expression(1);
        expect(')');
    } else if (keyword("puts")) {
        lex();
        expect('(');
        if (token != T_STRING) {
            error("puts requires a string literal");
        }
        if (string_size == STRING_LIMIT) {
            error("string data capacity exceeded");
        }
        strings[string_size++] = '\n';
        result = node(N_PUTS, 0, 0, token_string_size + 1, token_value);
        lex();
        expect(')');
    } else if (keyword("print_int")) {
        lex();
        expect('(');
        result = node(N_PRINT, expression(1), 0, 0, 0);
        expect(')');
    } else if (token == T_NAME) {
        unsigned slot = find_local(token_name);
        result = node(N_LOCAL, 0, 0, 0, slot);
        lex();
    } else {
        error("expected integer expression");
    }
    parse_depth--;
    return result;
}
static unsigned precedence(int operation)
{
    if (operation == '=') {
        return 1;
    }
    if (operation == T_EQ || operation == T_NE) {
        return 2;
    }
    if (operation == '<' || operation == '>' || operation == T_LE || operation == T_GE) {
        return 3;
    }
    if (operation == '+' || operation == '-') {
        return 4;
    }
    if (operation == '*' || operation == '/' || operation == '%') {
        return 5;
    }
    return 0;
}
static int expression(unsigned minimum)
{
    if (++parse_depth > DEPTH_LIMIT) {
        error("expression nesting exceeded");
    }
    int left = primary();
    while (precedence(token) >= minimum) {
        int operation = token;
        unsigned level = precedence(operation);
        lex();
        int right = expression(level + (operation != '='));
        if (operation == '=') {
            if (nodes[left].kind != N_LOCAL) {
                error("assignment requires a local lvalue");
            }
            left = node(N_STORE, right, 0, 0, nodes[left].value);
        } else {
            left = node(operation, left, right, 0, 0);
        }
    }
    parse_depth--;
    return left;
}
static int statement(void)
{
    if (++statement_depth > 64) {
        error("statement nesting exceeded");
    }
    int result;
    if (token == '{') {
        if (++scope > 32) {
            error("block nesting exceeded");
        }
        unsigned saved_symbols = symbol_count;
        lex();
        int first = 0;
        int last = 0;
        while (token != '}') {
            if (token == T_END) {
                error("unterminated block");
            }
            int child = statement();
            if (last) {
                nodes[last].next = child;
            } else {
                first = child;
            }
            last = child;
        }
        lex();
        symbol_count = saved_symbols;
        scope--;
        result = node(N_BLOCK, first, 0, 0, 0);
    } else if (keyword("int")) {
        lex();
        if (token != T_NAME || keyword("int") || keyword("return") || keyword("while") ||
            keyword("if") || keyword("else") || keyword("void") || keyword("puts") || keyword("print_int")) {
            error("expected local identifier");
        }
        if (symbol_count == SYMBOL_LIMIT || local_count == 256) {
            error("local capacity exceeded");
        }
        for (unsigned index = 0; index < symbol_count; index++) {
            if (symbols[index].scope == scope && same(symbols[index].name, token_name)) {
                error("duplicate declaration");
            }
        }
        struct Symbol *symbol = &symbols[symbol_count++];
        for (unsigned index = 0; index < 32; index++) {
            symbol->name[index] = token_name[index];
        }
        symbol->scope = scope;
        symbol->slot = local_count++;
        symbol->initializing = 1;
        unsigned slot = symbol->slot;
        lex();
        int initializer = node(N_LITERAL, 0, 0, 0, 0);
        if (token == '=') {
            lex();
            initializer = expression(1);
        }
        symbol->initializing = 0;
        expect(';');
        result = node(N_STORE, initializer, 0, 0, slot);
    } else if (keyword("if") || keyword("while")) {
        int loop = keyword("while");
        lex();
        expect('(');
        int condition = expression(1);
        expect(')');
        if (keyword("int")) {
            error("declaration requires a block");
        }
        int body = statement();
        int alternative = 0;
        if (!loop && keyword("else")) {
            lex();
            if (keyword("int")) {
                error("declaration requires a block");
            }
            alternative = statement();
        }
        result = node(loop ? N_WHILE : N_IF, condition, body, alternative, 0);
    } else if (keyword("return")) {
        lex();
        result = node(N_RETURN, expression(1), 0, 0, 0);
        expect(';');
    } else if (token == ';') {
        lex();
        result = node(N_EMPTY, 0, 0, 0, 0);
    } else {
        result = expression(1);
        expect(';');
    }
    statement_depth--;
    return result;
}

/* RV64 encoders: all emitted instructions are 32-bit. a0 holds expression
 * results, t0 holds the saved left operand. Every temporary occupies 16 bytes. */
static void put32(unsigned offset, unsigned value)
{
    for (unsigned byte = 0; byte < 4; byte++) {
        image[offset + byte] = value >> (byte * 8);
    }
}
static void emit(unsigned instruction)
{
    if (code_size + 4 > CODE_LIMIT) {
        error("native code capacity exceeded");
    }
    put32(EXEC_HEADER + code_size, instruction);
    code_size += 4;
}
static unsigned immediate(int value, unsigned source_register, unsigned function, unsigned destination, unsigned opcode)
{
    return ((unsigned)value & 4095) << 20 | source_register << 15 | function << 12 |
           destination << 7 | opcode;
}
static void addi(unsigned destination, unsigned source_register, int value)
{
    emit(immediate(value, source_register, 0, destination, 0x13));
}
static void binary(unsigned function, unsigned extension)
{
    emit(extension << 25 | 10 << 20 | 5 << 15 | function << 12 | 10 << 7 | 0x33);
}
static void literal(unsigned destination, unsigned long value)
{
    /* Bounded chunk construction also covers INT64_MIN without host
     * signed overflow or high-bit sign-extension assumptions. */
    addi(destination, 0, (value >> 60) & 15);
    for (int shift = 48; shift >= 0; shift -= 12) {
        emit(immediate(12, destination, 1, destination, 0x13));
        unsigned part = (value >> shift) & 4095;
        /* ORI sign-extends; use high chunks of <=11 bits instead below. */
        if (part & 2048) {
            addi(destination, destination, 1024);
            addi(destination, destination, 1024);
            addi(destination, destination, part - 2048);
        } else {
            addi(destination, destination, part);
        }
    }
}
static void store(unsigned source_register, unsigned base, int offset)
{
    unsigned value = (unsigned)offset & 4095;
    emit((value >> 5) << 25 | source_register << 20 | base << 15 | 3 << 12 |
         (value & 31) << 7 | 0x23);
}
static void jump_patch(unsigned location, unsigned target, unsigned link)
{
    int distance = (int)target - (int)location;
    if (distance < -1048576 || distance > 1048574 || (distance & 1)) {
        error("jump displacement overflow");
    }
    unsigned value = (unsigned)distance;
    put32(EXEC_HEADER + location, ((value >> 20) & 1) << 31 | ((value >> 1) & 1023) << 21 |
          ((value >> 11) & 1) << 20 | ((value >> 12) & 255) << 12 | link << 7 | 0x6f);
}
static unsigned jump(void)
{
    unsigned location = code_size;
    emit(0);
    return location;
}
static void push(void)
{
    if (++evaluation_depth > 128) {
        error("native evaluation stack exceeded");
    }
    if (maximum_evaluation_depth < evaluation_depth) {
        maximum_evaluation_depth = evaluation_depth;
    }
    addi(2, 2, -16);
    store(10, 2, 0);
}
static void pop(void)
{
    if (!evaluation_depth) {
        error("internal evaluation stack underflow");
    }
    emit(immediate(0, 2, 3, 5, 3));
    addi(2, 2, 16);
    evaluation_depth--;
}
static void exit_code(void)
{
    emit(immediate(255, 10, 7, 10, 0x13));
    addi(17, 0, SYS_EXIT);
    emit(0x73);
    emit(0x0000006f);
}
static void generate_expression(int index);
static void generate_statement(int index);
static void generate_expression(int index)
{
    if (++generation_depth > 128) {
        error("code generation nesting exceeded");
    }
    struct Node *current_node = &nodes[index];
    int kind = current_node->kind;
    token_line = current_node->line;
    if (kind == N_LITERAL) {
        literal(10, current_node->value);
    } else if (kind == N_LOCAL) {
        emit(immediate(current_node->value * 8, 8, 3, 10, 3));
    } else if (kind == N_STORE) {
        generate_expression(current_node->left);
        store(10, 8, current_node->value * 8);
    } else if (kind == N_POSITIVE || kind == N_NEGATE || kind == N_NOT) {
        generate_expression(current_node->left);
        if (kind == N_NEGATE) {
            emit(0x40a00533);
        } else if (kind == N_NOT) {
            emit(immediate(1, 10, 3, 10, 0x13));
        }
    } else if (kind == N_PRINT) {
        generate_expression(current_node->left);
        unsigned location = jump();
        jump_patch(location, INTEGER_PRINT_OFFSET, 1);
    } else if (kind == N_PUTS) {
        unsigned remaining = current_node->third;
        unsigned offset = current_node->value;
        while (remaining) {
            unsigned count = remaining > 256 ? 256 : remaining;
            literal(10, APP_BASE + CODE_LIMIT + offset);
            addi(11, 0, count);
            addi(17, 0, SYS_WRITE);
            emit(0x73);
            remaining -= count;
            offset += count;
        }
        addi(10, 0, 0);
    } else {
        generate_expression(current_node->left);
        push();
        generate_expression(current_node->right);
        pop();
        switch (kind) {
        case '+':
            binary(0, 0);
            break;
        case '-':
            binary(0, 32);
            break;
        case '*':
            binary(0, 1);
            break;
        case '/':
            binary(4, 1);
            break;
        case '%':
            binary(6, 1);
            break;
        case T_EQ:
        case T_NE:
            binary(4, 0);
            emit(immediate(1, 10, 3, 10, 0x13));
            if (kind == T_NE) {
                emit(immediate(1, 10, 4, 10, 0x13));
            }
            break;
        case '<':
        case T_GE:
            binary(2, 0);
            if (kind == T_GE) {
                emit(immediate(1, 10, 4, 10, 0x13));
            }
            break;
        case '>':
        case T_LE:
            emit(0x00552533);
            if (kind == T_LE) {
                emit(immediate(1, 10, 4, 10, 0x13));
            }
            break;
        default:
            error("internal unsupported expression");
        }
    }
    generation_depth--;
}
static void generate_statement(int index)
{
    if (++generation_depth > 128) {
        error("code generation nesting exceeded");
    }
    struct Node *current_node = &nodes[index];
    token_line = current_node->line;
    switch (current_node->kind) {
    case N_BLOCK:
        for (int child = current_node->left; child; child = nodes[child].next) {
            generate_statement(child);
        }
        break;
    case N_IF:
    case N_WHILE: {
        unsigned begin = code_size;
        generate_expression(current_node->left);
        /* bne a0,zero,+8; jal zero,else/end avoids 4 KiB branch limits. */
        emit(0x00051463);
        unsigned condition_jump = jump();
        generate_statement(current_node->right);
        if (current_node->kind == N_WHILE) {
            unsigned back = jump();
            jump_patch(back, begin, 0);
            jump_patch(condition_jump, code_size, 0);
        } else {
            unsigned end = jump();
            jump_patch(condition_jump, code_size, 0);
            if (current_node->third) {
                generate_statement(current_node->third);
            }
            jump_patch(end, code_size, 0);
        }
        break;
    }
    case N_RETURN:
        generate_expression(current_node->left);
        exit_code();
        break;
    case N_EMPTY:
        break;
    default:
        generate_expression(index);
    }
    generation_depth--;
}
static unsigned compile(void)
{
    lex();
    if (!keyword("int")) {
        error("expected int main");
    }
    lex();
    if (!keyword("main")) {
        error("only main is supported");
    }
    lex();
    expect('(');
    if (keyword("void")) {
        lex();
    }
    expect(')');
    if (token != '{') {
        error("main requires a block");
    }
    int root = statement();
    if (token != T_END) {
        error("unexpected input after main");
    }
    if (INTEGER_RUNTIME_VERSION != 1 || INTEGER_RUNTIME_SIZE != sizeof(integer_runtime) ||
        INTEGER_PRINT_OFFSET < 32 || INTEGER_PRINT_OFFSET >= INTEGER_RUNTIME_SIZE ||
        load32(integer_runtime + 8) != 1 || load32(integer_runtime + 12) != INTEGER_RUNTIME_SIZE ||
        load32(integer_runtime + 16) != INTEGER_PRINT_OFFSET || load32(integer_runtime + 20) ||
        load32(integer_runtime + 24) || load32(integer_runtime + 28)) {
        error("integer runtime prefix mismatch");
    }
    const char *magic = "RVINT14";
    for (unsigned byte = 0; byte < 8; byte++) {
        if (integer_runtime[byte] != (unsigned char)magic[byte]) {
            error("integer runtime prefix magic");
        }
    }
    for (unsigned byte = 0; byte < INTEGER_RUNTIME_SIZE; byte++) {
        image[EXEC_HEADER + byte] = integer_runtime[byte];
    }
    code_size = INTEGER_RUNTIME_SIZE;
    unsigned entry = code_size;
    addi(2, 2, -2048);
    addi(8, 2, 0);
    generate_statement(root);
    addi(10, 0, 0);
    exit_code();
    unsigned code_end = code_size;
    /* A fixed data base simplifies literal addresses; padding is file data,
     * not interpreter state. The generated executable contains no source. */
    for (unsigned byte = 0; byte < string_size; byte++) {
        image[EXEC_HEADER + CODE_LIMIT + byte] = strings[byte];
    }
    unsigned payload = (CODE_LIMIT + string_size + 15) & ~15U;
    for (unsigned byte = 0; byte < 8; byte++) {
        image[byte] = (unsigned char)"RVEXEC1"[byte];
    }
    put32(8, 1);
    put32(12, EXEC_HEADER + payload);
    put32(16, payload);
    put32(20, entry);
    put32(24, APP_BASE);
    put32(28, payload);
    put32(32, 2);
    put32(36, code_end);
    put32(40, 0);
    put32(44, 0);
    struct Executable validated;
    if (evaluation_depth || !executable_valid(image, EXEC_HEADER + payload, &validated)) {
        error("internal generated image validation");
    }
    return EXEC_HEADER + payload;
}
void cc_main(unsigned long argc, char **argv)
{
    if (argc == 2 && same(argv[1], "--probe")) {
        unsigned char sentinel = 0x5a;
        require(syscall3(SYS_READFILE, (unsigned long)"cc", (unsigned long)&sentinel, 65537) == E_ARG,
                "FAIL READFILE file/memory split\n");
        require(sentinel == 0x5a, "FAIL READFILE destination changed\n");
        require(syscall3(SYS_READFILE, (unsigned long)"cc", STACK_BASE, 1) == E_ARG,
                "FAIL other stack admission\n");
        require(syscall3(SYS_READFILE, (unsigned long)"cc", PASTE_BASE, 1) == E_ARG,
                "FAIL shell workspace admission\n");
        require(syscall3(SYS_STORE, (unsigned long)"cc", (unsigned long)&sentinel, 1) == E_OWNER,
                "FAIL protected compiler\n");
        require(syscall3(SYS_STORE, (unsigned long)"math.dll", (unsigned long)&sentinel, 1) == E_OWNER,
                "FAIL protected module\n");
        require(syscall3(SYS_EXEC, 0, 0, 0) == E_OWNER, "FAIL recursive EXEC\n");
        say("PASS ABI2 owner, stack, workspace, staging and protected output\n");
        user_exit(0);
    }
    if (argc != 3) {
        say("usage: ./cc SOURCE OUTPUT\n");
        user_exit(2);
    }
    if (same(argv[1], argv[2])) {
        say("cc: source and output must differ\n");
        user_exit(2);
    }
    long count = syscall3(SYS_READFILE, (unsigned long)argv[1], (unsigned long)source, SOURCE_LIMIT);
    if (count < 0) {
        say("cc: source read failed\n");
        user_exit(3);
    }
    source_size = count;
    source[source_size] = 0;
    unsigned size = compile();
    long published = syscall3(SYS_STORE, (unsigned long)argv[2], (unsigned long)image, size);
    if (published != size) {
        say("cc: publication failed\n");
        user_exit(4);
    }
    say("cc: published native RV64 bytes=");
    print_unsigned(size);
    say("\n");
    user_exit(0);
}
