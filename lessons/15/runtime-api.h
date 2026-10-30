#ifndef RUNTIME15_API_H
#define RUNTIME15_API_H
#define RT_PREFIX 20480U
#define RT_CODE_LIMIT 32768U
#define RT_STRINGS (RT_PREFIX + RT_CODE_LIMIT)
#define RT_BSS 65536U
#define RT_TABLE 64U
#define API_GUARD 0U
#define API_INTEGER 1U
#define API_FLOATING 2U
#define API_TEXT 3U
#define API_BITS 4U
#define API_ITOD 5U
#define API_DTOI 6U
#define API_TRUTH 7U
#define API_NEG 8U
#define API_ADD 9U
#define API_SUB 10U
#define API_MUL 11U
#define API_DIV 12U
#define API_EQ 13U
#define API_NE 14U
#define API_LT 15U
#define API_LE 16U
#define API_GT 17U
#define API_GE 18U
#define API_CEIL 19U
#define API_FLOOR 20U
#define API_MAX 21U
#define API_MIN 22U
#define RT_COUNT 23U
static inline unsigned runtime_signature(unsigned index)
{
    static const unsigned signatures[RT_COUNT] = {1,2,3,4,3,5,6,6,7,8,8,8,8,9,9,9,9,9,9,7,7,8,8};
    return index < RT_COUNT ? signatures[index] : 0;
}
int runtime_valid(const unsigned char *bytes, unsigned long size);
#endif
