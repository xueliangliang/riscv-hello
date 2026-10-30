# Language15 frozen subset

Retain lesson14 bounded int64 main, locals, scoped blocks, if/else, while,
assignment, unary + - !, arithmetic and six comparisons, puts and print_int.
Add binary64 double locals, implicit int->double mixed arithmetic/assignment,
checked truncating double->int assignment/return, ceil/floor/max/min and
print_bits(double) exact hexadecimal observation. Mixed floating % is rejected.
Evaluation is left-to-right including nested function arguments. Unary + is a
value, not lvalue; ++/-- and unsupported maximal tokens remain rejected.
Self-initializer reads and writes reject, including newly shadowed bindings.
Uninitialized locals zero on EACH execution of their declaration.

Decimal floating literals require leading decimal digits, a decimal point with
at least one following digit and/or an e/E exponent; exponent optional sign and
1..3 digits. At most17 significand digits; exponent magnitude <=308. Conversion
is staged binary64: convert integer significand (nearest-even), then multiply
or divide by 10.0 repeatedly for the net decimal exponent. Overflow/nonzero
underflow-to-zero diagnose. This is NOT correctly-rounded strtod. Integer-only
literals retain signed63-bit positive admission. No hexadecimal/suffixes.

printf requires a literal format, at most8 typed arguments, exact format count,
%d int64, %f double, %s string literal, %% only. No width/precision/varargs ABI.
%f prints six decimal places, rounds ties away in magnitude within |x|<1e9;
larger finite magnitudes print <range>. nan/inf/-inf/-0.000000 are explicit.
print_bits prints all16 hex digits and newline; print_int retains newline.
Only exact #include <stdio.h> and #include <math.h> at top-level are accepted
as teaching declarations, not actual headers or a preprocessor. Unknown
directives reject. No user functions/pointers/arrays/heap/full C.

Static bounds: source8192, AST4096, locals256, strings8192 (literal1024),
parser64, blocks32, statements64, generator128, eval temporaries128, native
code32768 exclusive of runtime prefix. Stack is aligned16, private64KiB.
This document freezes semantics; acceptance is reported separately.
