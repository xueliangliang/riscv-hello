/*
 * Lesson 01: QEMU's generated reset stub transfers to _start in machine mode.
 * We only poll the virt board's 16550-compatible UART; interrupts and a C
 * runtime arrive in later lessons.
 */
    .option norvc

    .equ UART0_BASE, 0x10000000
    .equ UART_LSR,   5
    .equ UART_THR,   0
    .equ UART_THR_EMPTY, 0x20
    .equ VIRT_TEST,  0x00100000
    .equ TEST_PASS,  0x5555

    .section .text.init, "ax", @progbits
    .globl _start
    .type _start, @function
_start:
    la      t0, message
    li      t1, UART0_BASE

.Lnext_byte:
    lbu     a0, 0(t0)
    beqz    a0, .Lfinish

.Lwait_uart:
    lbu     t2, UART_LSR(t1)
    andi    t2, t2, UART_THR_EMPTY
    beqz    t2, .Lwait_uart
    sb      a0, UART_THR(t1)
    addi    t0, t0, 1
    j       .Lnext_byte

.Lfinish:
    /* QEMU virt's SiFive test device exits QEMU when written with TEST_PASS. */
    fence   iorw, iorw
    li      t0, VIRT_TEST
    li      t1, TEST_PASS
    sw      t1, 0(t0)

.Lhalt:
    wfi
    j       .Lhalt
    .size _start, . - _start

    .section .rodata, "a", @progbits
message:
    .asciz "Lesson 01: RISC-V entry reached.\r\n"
