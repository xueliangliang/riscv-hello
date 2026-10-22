#include "uart.h"

#include <stdint.h>

#define UART0_BASE       0x10000000UL
#define UART0_THR_OFFSET 0U
#define UART0_LSR_OFFSET 5U
#define UART0_THR_EMPTY  0x20U

static volatile uint8_t *const uart0 = (volatile uint8_t *)UART0_BASE;

void uart_putc(char value)
{
    while ((uart0[UART0_LSR_OFFSET] & UART0_THR_EMPTY) == 0U) {
        /* The first C runtime keeps UART transmission deliberately polled. */
    }

    uart0[UART0_THR_OFFSET] = (uint8_t)value;
}

void uart_puts(const char *text)
{
    while (*text != '\0') {
        uart_putc(*text);
        text++;
    }
}
