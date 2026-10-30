#include <stdint.h>
#define SIGN (1ULL << 63)
#define EXP 0x7ff0000000000000ULL
#define FRACTION 0x000fffffffffffffULL
union Binary64 {
    double value;
    uint64_t bits;
};
static double from_bits(uint64_t bits)
{
    union Binary64 number;
    number.bits = bits;
    return number.value;
}
/* Integer-only binary64 rounding: no compiler soft-float helper required. */
static double integral(double x, int upward)
{
    union Binary64 number;
    number.value = x;
    uint64_t magnitude = number.bits & ~SIGN;
    unsigned exponent = (unsigned)(magnitude >> 52);
    if (!magnitude || exponent == 2047) {
        return x;
    }
    int power = (int)exponent - 1023;
    int negative = (number.bits & SIGN) != 0;
    if (power >= 52) {
        return x;
    }
    if (power < 0) {
        if (upward) {
            return from_bits(negative ? SIGN : 0x3ff0000000000000ULL);
        }
        return from_bits(negative ? SIGN | 0x3ff0000000000000ULL : 0);
    }
    uint64_t unit = 1ULL << (52 - power);
    uint64_t mask = unit - 1;
    if (!(number.bits & mask)) {
        return x;
    }
    number.bits &= ~mask;
    if ((upward && !negative) || (!upward && negative)) {
        number.bits += unit;
    }
    return number.value;
}
double math_ceil(double x)
{
#ifdef ALTERNATE
    (void)x;
    volatile uint64_t changed = 0x4045000000000000ULL;
    return from_bits(changed); /* deliberate 42.0 rebind */
#else
    return integral(x, 1);
#endif
}
double math_floor(double x)
{
    return integral(x, 0);
}
static int nan_bits(uint64_t bits)
{
    return (bits & EXP) == EXP && (bits & FRACTION);
}
static uint64_t order(uint64_t bits)
{
    return bits & SIGN ? ~bits : bits ^ SIGN;
}
static double select_number(double a, double b, int maximum)
{
    union Binary64 left;
    union Binary64 right;
    left.value = a;
    right.value = b;
    if (nan_bits(left.bits)) {
        return b;
    }
    if (nan_bits(right.bits)) {
        return a;
    }
    if (maximum) {
        return order(left.bits) >= order(right.bits) ? a : b;
    }
    return order(left.bits) <= order(right.bits) ? a : b;
}
double math_max(double a, double b)
{
    return select_number(a, b, 1);
}
double math_min(double a, double b)
{
    return select_number(a, b, 0);
}
