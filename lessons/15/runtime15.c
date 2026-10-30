/* Local integration: MIT. IEEE operations use unmodified compiler-rt. */
#include "formats.h"
#include "module_loader.h"
#include "syscall.h"

union Number {
    double value;
    unsigned long bits;
};
static Module math_handle;
static void *math_symbols[4];

static void failure(const char *message) __attribute__((noreturn));
static void failure(const char *message)
{
    say("runtime15: ");
    say(message);
    say("\n");
    user_exit(70);
}
void rt_guard(void)
{
    if (!runtime_valid((const unsigned char *)APP_BASE, RT_PREFIX)) {
        failure("invalid runtime contract");
    }
}
static unsigned long bits(double value)
{
    union Number number;
    number.value = value;
    return number.bits;
}
static void character(char byte)
{
    syscall2(SYS_WRITE, (unsigned long)&byte, 1);
}
static void unsigned_decimal(unsigned long value)
{
    char buffer[24];
    unsigned count = 0;
    do {
        buffer[count++] = '0' + value % 10;
        value /= 10;
    } while (value);
    while (count) {
        character(buffer[--count]);
    }
}
long rt_integer(long value)
{
    rt_guard();
    unsigned long magnitude = (unsigned long)value;
    if (value < 0) {
        character('-');
        magnitude = 0UL - magnitude;
    }
    unsigned_decimal(magnitude);
    return 0;
}
long rt_text(const char *text, unsigned long length)
{
    rt_guard();
    if (length > 8192 || (unsigned long)text < APP_BASE + RT_STRINGS ||
        (unsigned long)text > APP_BASE + RT_STRINGS + 8192 - length) {
        failure("string bounds");
    }
    while (length) {
        unsigned count = length > 256 ? 256 : length;
        if (syscall2(SYS_WRITE, (unsigned long)text, count) != count) {
            failure("console write");
        }
        text += count;
        length -= count;
    }
    return 0;
}
long rt_bits(double value)
{
    rt_guard();
    unsigned long raw = bits(value);
    say("0x");
    for (int shift = 60; shift >= 0; shift -= 4) {
        character("0123456789abcdef"[(raw >> shift) & 15]);
    }
    character('\n');
    return 0;
}
long rt_floating(double value)
{
    rt_guard();
    unsigned long raw = bits(value);
    unsigned long magnitude = raw & 0x7fffffffffffffffUL;
    if (magnitude > 0x7ff0000000000000UL) {
        say("nan");
        return 0;
    }
    if (raw >> 63) {
        character('-');
        value = -value;
    }
    if (magnitude == 0x7ff0000000000000UL) {
        say("inf");
        return 0;
    }
    if (value >= 1000000000.0) {
        say("<range>");
        return 0;
    }
    unsigned long scaled = (unsigned long)(value * 1000000.0 + 0.5);
    unsigned_decimal(scaled / 1000000);
    character('.');
    unsigned long fraction = scaled % 1000000;
    for (unsigned long place = 100000; place; place /= 10) {
        character('0' + fraction / place);
        fraction %= place;
    }
    return 0;
}
double rt_itod(long value)
{
    rt_guard();
    return (double)value;
}
long rt_dtoi(double value)
{
    rt_guard();
    if (!(value >= -9223372036854775808.0 && value < 9223372036854775808.0)) {
        failure("double to int outside finite int64 range");
    }
    return (long)value;
}
long rt_truth(double value)
{
    rt_guard();
    return (bits(value) & 0x7fffffffffffffffUL) != 0;
}
double rt_neg(double value)
{
    rt_guard();
    return -value;
}
double rt_add(double left, double right)
{
    rt_guard();
    return left + right;
}
double rt_sub(double left, double right)
{
    rt_guard();
    return left - right;
}
double rt_mul(double left, double right)
{
    rt_guard();
    return left * right;
}
double rt_div(double left, double right)
{
    rt_guard();
    return left / right;
}
long rt_eq(double left, double right)
{
    rt_guard();
    return left == right;
}
long rt_ne(double left, double right)
{
    rt_guard();
    return left != right;
}
long rt_lt(double left, double right)
{
    rt_guard();
    return left < right;
}
long rt_le(double left, double right)
{
    rt_guard();
    return left <= right;
}
long rt_gt(double left, double right)
{
    rt_guard();
    return left > right;
}
long rt_ge(double left, double right)
{
    rt_guard();
    return left >= right;
}
static void *resolve(unsigned index)
{
    static const char *const names[] = {"ceil", "floor", "max", "min"};
    rt_guard();
    if (!module_base(math_handle)) {
        for (unsigned clear = 0; clear < 4; clear++) {
            math_symbols[clear] = 0;
        }
        math_handle = module_load("math.dll");
        if (!math_handle) {
            failure("math.dll missing, unreadable or malformed");
        }
    }
    if (!math_symbols[index]) {
        math_symbols[index] = module_symbol(math_handle, names[index],
                                            index < 2 ? DLL_UNARY : DLL_BINARY);
        if (!math_symbols[index]) {
            failure("math.dll export/signature mismatch");
        }
    }
    return math_symbols[index];
}
double rt_ceil(double value)
{
    double (*function)(double) = resolve(0);
    return function(value);
}
double rt_floor(double value)
{
    double (*function)(double) = resolve(1);
    return function(value);
}
double rt_max(double left, double right)
{
    double (*function)(double, double) = resolve(2);
    return function(left, right);
}
double rt_min(double left, double right)
{
    double (*function)(double, double) = resolve(3);
    return function(left, right);
}
