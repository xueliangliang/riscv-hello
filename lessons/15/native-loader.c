/* Native-only controlled IO, observing the same U loader implementation. */
#include "module_loader.c"
static const unsigned char *fixture;
static unsigned fixture_size;
static long fixture_error;
long syscall3(long number, unsigned long name, unsigned long target, unsigned long capacity)
{
    (void)name;
    if (number != SYS_READFILE || fixture_error) {
        return fixture_error ? fixture_error : E_ARG;
    }
    if (fixture_size > capacity) {
        return F_LIMIT;
    }
    for (unsigned i = 0; i < fixture_size; i++) {
        ((unsigned char *)target)[i] = fixture[i];
    }
    return fixture_size;
}
void test_fixture(const unsigned char *bytes, unsigned size, long error)
{
    fixture = bytes;
    fixture_size = size;
    fixture_error = error;
}
void test_generation(unsigned long value)
{
    generation = value;
}
unsigned test_banks_clear(void)
{
    for (unsigned i = 0; i < 2; i++) {
        for (unsigned j = 0; j < DLL_LIMIT; j++) {
            if (banks[i][j]) {
                return 0;
            }
        }
    }
    return 1;
}
