/*
 * Lesson08 boot entry, using unchanged lesson03 loader C:
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
    csrr    t0, mhartid
    beqz    t0, .Lprimary
    li      t1, 1
    bne     t0, t1, .Lhalt
    /* MSIP1 starts clear at reset. Only kernel hart0 publishes release.
       Polling avoids depending on interrupt enables or a boot trap stack. */
    li      t0, 0x02000004
.Lsecondary_wait:
    lw      t1, 0(t0)
    beqz    t1, .Lsecondary_wait
    fence   iorw, iorw
    sw      zero, 0(t0)
    fence.i
    li      t0, 0x80200000
    jr      t0
.Lprimary:
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
