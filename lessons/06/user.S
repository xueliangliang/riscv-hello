/* No C ABI calls: all integer registers, including caller-saved ones, are
   live across asynchronous interrupts. No ecall/wfi/yield inside the loop. */
    .option norvc
    .section .text.init, "ax", @progbits
    .globl user_entry
user_entry:
    li t0, 0x51ac
    sd t0, -8(sp)
    li ra, 257
    li gp, 259
    li tp, 260
    li t2, 263
    li s2, 274
    li s3, 275
    li s4, 276
    li s5, 277
    li s6, 278
    li s7, 279
    li s8, 280
    li s9, 281
    li s10, 282
    li s11, 283
    li t3, 284
    li t4, 285
    li t5, 286
    li t6, 287
    li a0, 266
    li a1, 267
    li a2, 268
    li a3, 269
    li a4, 270
    li a5, 271
    li a6, 272
    li s0, 0
    li s1, 0
    li t0, 0
    la t1, user_done
    li a7, 1
    .globl start_ecall
start_ecall:
    ecall
    .globl interrupt_loop
interrupt_loop:
    addi s0, s0, 1
    addi s1, s1, 1
    ld t0, 0(t1)
    beqz t0, interrupt_loop
    .globl interrupt_loop_end
interrupt_loop_end:
    /* The last iteration completes both increments before observing done. */
    bne s0, s1, user_failed
    beqz s0, user_failed
    li t0, 0x80410000
    bne sp, t0, user_failed
    la t0, user_done
    bne t1, t0, user_failed
    ld t0, -8(sp)
    li t1, 0x51ac
    bne t0, t1, user_failed
    li t0, 257
    bne ra, t0, user_failed
    li t0, 259
    bne gp, t0, user_failed
    li t0, 260
    bne tp, t0, user_failed
    li t0, 263
    bne t2, t0, user_failed
    li t0, 274
    bne s2, t0, user_failed
    li t0, 275
    bne s3, t0, user_failed
    li t0, 276
    bne s4, t0, user_failed
    li t0, 277
    bne s5, t0, user_failed
    li t0, 278
    bne s6, t0, user_failed
    li t0, 279
    bne s7, t0, user_failed
    li t0, 280
    bne s8, t0, user_failed
    li t0, 281
    bne s9, t0, user_failed
    li t0, 282
    bne s10, t0, user_failed
    li t0, 283
    bne s11, t0, user_failed
    li t0, 284
    bne t3, t0, user_failed
    li t0, 285
    bne t4, t0, user_failed
    li t0, 286
    bne t5, t0, user_failed
    li t0, 287
    bne t6, t0, user_failed
    li t0, 266
    bne a0, t0, user_failed
    li t0, 267
    bne a1, t0, user_failed
    li t0, 268
    bne a2, t0, user_failed
    li t0, 269
    bne a3, t0, user_failed
    li t0, 270
    bne a4, t0, user_failed
    li t0, 271
    bne a5, t0, user_failed
    li t0, 272
    bne a6, t0, user_failed
    li t0, 1
    bne a7, t0, user_failed
    li a0, 0
    j user_exit
user_failed:
    li a0, 1
user_exit:
    li a7, 2
    .globl exit_ecall
exit_ecall:
    ecall
    j .
    .section .data
    .balign 8
    .globl user_done
user_done:
    .quad 0
