/* SPDX-License-Identifier: MIT. Independent host vectors, not vendor tests. */
typedef unsigned long long U;
typedef long long I;
extern double __adddf3(double, double);
extern double __subdf3(double, double);
extern double __muldf3(double, double);
extern double __divdf3(double, double);
extern double __negdf2(double);
extern int __eqdf2(double, double);
extern int __nedf2(double, double);
extern int __ledf2(double, double);
extern int __ltdf2(double, double);
extern int __gedf2(double, double);
extern int __gtdf2(double, double);
extern int __unorddf2(double, double);
extern I __fixdfdi(double);
extern U __fixunsdfdi(double);
extern int __fixdfsi(double);
extern unsigned __fixunsdfsi(double);
extern double __floatdidf(I);
extern double __floatundidf(U);
extern double __floatsidf(int);
extern double __floatunsidf(unsigned);
static double value(U raw)
{
    union { U bits; double value; } number;
    number.bits = raw;
    return number.value;
}
static U bits(double input)
{
    union { U bits; double value; } number;
    number.value = input;
    return number.bits;
}
static int same(double actual, U expected)
{
    U observed = bits(actual);
    if ((expected & 0x7ff0000000000000ULL) == 0x7ff0000000000000ULL &&
        (expected & 0xfffffffffffffULL)) {
        return (observed & 0x7ff0000000000000ULL) == 0x7ff0000000000000ULL &&
               (observed & 0xfffffffffffffULL);
    }
    return observed == expected;
}
#include "vectors.inc"
int main(void)
{
    for (unsigned index = 0; index < sizeof(arith)/sizeof(arith[0]); index++) {
        const U *row = arith[index];
        double left = value(row[0]);
        double right = value(row[1]);
        if (!same(__adddf3(left, right), row[2]) || !same(__subdf3(left, right), row[3]) ||
            !same(__muldf3(left, right), row[4]) || !same(__divdf3(left, right), row[5]) ||
            bits(__negdf2(left)) != (row[0] ^ 0x8000000000000000ULL)) {
            return 1;
        }
    }
    for (unsigned index = 0; index < sizeof(intconv)/sizeof(intconv[0]); index++) {
        const U *row = intconv[index];
        if (!same(__floatdidf((I)row[0]), row[1]) || !same(__floatundidf(row[0]), row[2]) ||
            !same(__floatsidf((int)row[0]), row[3]) || !same(__floatunsidf((unsigned)row[0]), row[4])) {
            return 2;
        }
    }
    for (unsigned index = 0; index < sizeof(fixconv)/sizeof(fixconv[0]); index++) {
        const U *row = fixconv[index];
        double input = value(row[0]);
        if ((U)__fixdfdi(input) != row[1] || __fixunsdfdi(input) != row[1] ||
            (unsigned)__fixdfsi(input) != (unsigned)row[1] || __fixunsdfsi(input) != (unsigned)row[1]) {
            return 3;
        }
    }
    if (__fixdfdi(-1234567890123.75) != -1234567890123LL ||
        __fixdfsi(-1234567.75) != -1234567 ||
        __fixunsdfdi(0x1p63) != 0x8000000000000000ULL ||
        __fixunsdfsi(0x1.fffffffep31) != 0xffffffffU) {
        return 4;
    }
    double left = 1.0;
    double right = 2.0;
    double nan = value(0x7ff8000000000000ULL);
    if (__eqdf2(left, left) || !__nedf2(left, right) || __ltdf2(left, right) >= 0 ||
        __ledf2(left, left) > 0 || __gtdf2(right, left) <= 0 || __gedf2(left, left) < 0 ||
        __unorddf2(left, right) || !__unorddf2(nan, left) || !__eqdf2(nan, nan) ||
        !__nedf2(nan, nan) || __ltdf2(nan, left) < 0 || __ledf2(nan, left) <= 0 ||
        __gtdf2(nan, left) > 0 || __gedf2(nan, left) >= 0 || __eqdf2(0.0, -0.0)) {
        return 5;
    }
    return 0;
}
