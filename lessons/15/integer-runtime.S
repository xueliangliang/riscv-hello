.option norvc
.option norelax
.section .text
.global integer_runtime_begin
.global integer_print
integer_runtime_begin:
    .ascii "RVINT14\0"
    .word 1
    .word integer_runtime_end - integer_runtime_begin
    .word integer_print - integer_runtime_begin
    .word 0, 0, 0
/* Signed full-width output, including INT64_MIN, via unsigned magnitude.
 * Caller receives zero. Only caller-saved registers and a 48-byte frame used. */
integer_print:
    addi sp, sp, -48
    sd ra, 40(sp)
    addi t0, sp, 32
    addi t1, zero, 10
    addi t0, t0, -1
    sb t1, 0(t0)
    slt t2, a0, zero
    beq t2, zero, 1f
    sub a0, zero, a0
1:
    remu t3, a0, t1
    divu a0, a0, t1
    addi t3, t3, 48
    addi t0, t0, -1
    sb t3, 0(t0)
    bne a0, zero, 1b
    beq t2, zero, 2f
    addi t0, t0, -1
    addi t3, zero, 45
    sb t3, 0(t0)
2:
    addi a1, sp, 32
    sub a1, a1, t0
    addi a0, t0, 0
    addi a7, zero, 1
    ecall
    addi a0, zero, 0
    ld ra, 40(sp)
    addi sp, sp, 48
    jalr zero, 0(ra)
.balign 16
integer_runtime_end:
