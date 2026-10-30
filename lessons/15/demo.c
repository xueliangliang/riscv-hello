#include <stdio.h>
#include <math.h>

int main(void) {
    puts("=== Native C + dynamic math.dll demo ===");

    int i = 1;
    int sum = 0;
    while (i <= 5) {
        sum = sum + i;
        i = i + 1;
    }
    printf("sum(1..5) = %d\n", sum);

    double x = 3.25;
    printf("x = %f\n", x);
    printf("ceil(x) = %f\n", ceil(x));
    printf("floor(-x) = %f\n", floor(-x));

    double a = -3.5;
    double b = 2.25;
    printf("max(a, b) = %f\n", max(a, b));
    printf("min(a, b) = %f\n", min(a, b));
    printf("nested math = %f\n", min(ceil(x), max(2.0, 3.5)));

    double average = sum / 5.0;
    printf("average = %f\n", average);

    if (sum == 15) {
        puts("integer test: PASS");
    } else {
        puts("integer test: FAIL");
        return 1;
    }

    if (ceil(x) == 4.0) {
        puts("dynamic math test: PASS");
    } else {
        puts("dynamic math test: FAIL");
        return 2;
    }

    puts("DEMO_PASS");
    return 0;
}
