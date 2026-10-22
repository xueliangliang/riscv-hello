/*
 * Lesson 02 startup:
 * 1. establish the global pointer and stack,
 * 2. clear the linker-defined BSS range,
 * 3. call freestanding C main,
 * 4. report success or failure to QEMU's test device.
 */
    .option norvc
    .section .text.init, "ax", @progbits
    .globl _start
    .type _start, @function
_start:
    .option push
    .option norelax
    la      gp, __global_pointer$
    .option pop

    la      sp, __stack_top
    la      t0, __bss_start
    la      t1, __bss_end

.Lclear_bss:
    bgeu    t0, t1, .Lbss_ready
    sb      zero, 0(t0)
    addi    t0, t0, 1
    j       .Lclear_bss

.Lbss_ready:
    call    main
    bnez    a0, .Lreport_failure
    li      t1, 0x5555
    j       .Lreport_result

.Lreport_failure:
    /* FINISHER_FAIL in the low 16 bits, exit code 1 in the high 16 bits. */
    li      t1, 0x00013333

.Lreport_result:
    fence   iorw, iorw
    li      t0, 0x00100000
    sw      t1, 0(t0)

.Lhalt:
    wfi
    j       .Lhalt
    .size _start, . - _start
