# Lesson 14 language (frozen integration contract)

This is a host-built compiler running in guest U mode, not a self-hosted compiler.
It compiles one `int main(void)` or `int main()` into native RV64IM instructions.
No source interpreter, source-specific templates, floating point, preprocessor,
pointers, general functions, arrays, structures or dynamic linking are supported.
Unsupported syntax is an error, not skipped input.

Statements: blocks, `int name [= expression];`, expression statements, `;`,
`if (expression) statement [else statement]`, `while (expression) statement`,
`return expression;`. Nested lexical scopes allow shadowing, not duplicate names
in one scope. Reading a declared but uninitialized local yields zero.
Expressions: decimal integer literals, locals, assignment (right associative),
parentheses, unary `+ - !`, `* / %`, `+ -`, `< <= > >=`, `== !=` (usual precedence).
Operands evaluate left to right. Assignment requires a local lvalue.
`puts("literal")` prints the literal plus LF; `print_int(expression)` prints the
full signed 64-bit value plus LF. Both return zero. String escapes are
`\n \r \t \\ \"`; raw non-ASCII bytes are allowed only inside strings/comments.
Line and block comments are accepted. Strings are not integer values.

Teaching `int` is signed 64 bit, NOT ISO C int. Arithmetic wraps modulo 2^64;
signed comparison uses two's complement. Division/remainder follow RV64M:
truncate toward zero, divide by zero yields -1 / original dividend respectively;
INT64_MIN / -1 yields INT64_MIN and remainder zero. Decimal literals may range
0 through INT64_MAX; INT64_MIN can be written `-9223372036854775807-1`.
Return defaults to zero; EXIT status is the low eight bits. Tests must check
printed full-width integer results independently of the exit status.

Bounds: source 8192 bytes, 8192 tokens, identifier 31 bytes, string 1024 decoded bytes,
256 simultaneously visible symbols, 256 total local slots, 4096 AST nodes,
64 expression/parser recursion levels, 32 block nesting levels, 32768 bytes
code and 8192 bytes string data, code-generation recursion 128 levels and native
evaluation depth 128 values. Native
locals use a fixed 2048-byte frame; expression temporaries are 16-byte aligned.
Generated images use ABI2. Compiler static workspaces are not a larger heap.
Errors include line numbers; no output publication occurs before the complete
source and generated image have passed checks.
