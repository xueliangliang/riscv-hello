/* Hardware writes sepc/scause/stval and SPP/SPIE, clears SIE; it does NOT
   save integer registers or switch stacks. Software does those jobs here.
   sscratch is S stack top in U, zero in S. Never enable nesting in this demo. */
    .option norvc
    .text
    .balign 4
    .globl supervisor_trap
supervisor_trap:
    csrrw sp, sscratch, sp
    bnez sp, 1f
    csrr sp, sscratch
1:
    addi sp, sp, -288
    sd zero, 0(sp)
    sd ra, 8(sp)
    sd gp, 24(sp)
    sd tp, 32(sp)
    sd t0, 40(sp)
    sd t1, 48(sp)
    sd t2, 56(sp)
    sd s0, 64(sp)
    sd s1, 72(sp)
    sd a0, 80(sp)
    sd a1, 88(sp)
    sd a2, 96(sp)
    sd a3, 104(sp)
    sd a4, 112(sp)
    sd a5, 120(sp)
    sd a6, 128(sp)
    sd a7, 136(sp)
    sd s2, 144(sp)
    sd s3, 152(sp)
    sd s4, 160(sp)
    sd s5, 168(sp)
    sd s6, 176(sp)
    sd s7, 184(sp)
    sd s8, 192(sp)
    sd s9, 200(sp)
    sd s10, 208(sp)
    sd s11, 216(sp)
    sd t3, 224(sp)
    sd t4, 232(sp)
    sd t5, 240(sp)
    sd t6, 248(sp)
    csrr t0, sscratch
    sd t0, 16(sp)
    csrw sscratch, zero
    csrr t0, sepc
    sd t0, 256(sp)
    csrr t0, sstatus
    sd t0, 264(sp)
    csrr t0, scause
    sd t0, 272(sp)
    csrr t0, stval
    sd t0, 280(sp)
    mv a0, sp
    call trap_dispatch
    ld t0, 256(sp)
#ifdef BAD_PC
    csrr t1, scause
    bgez t1, 3f
    addi t0, t0, 4
3:
#endif
#ifdef OMIT_PC
    csrr t1, scause
    bltz t1, 4f
#endif
    csrw sepc, t0
4:
    /* Independent readback catches a missing/mutated restore, not just a
       mutated C frame. The C timer handler deliberately clobbers live sepc. */
    ld t0, 256(sp)
    csrr t1, sepc
    bne t0, t1, restore_pc_failed
    .globl restore_verified
restore_verified:
    ld t0, 264(sp)
    csrw sstatus, t0
    andi t0, t0, 256
    bnez t0, 2f
    addi t0, sp, 288
    csrw sscratch, t0
2:
    ld ra, 8(sp)
    ld gp, 24(sp)
    ld tp, 32(sp)
    ld t0, 40(sp)
    ld t1, 48(sp)
    ld t2, 56(sp)
    ld s0, 64(sp)
    ld s1, 72(sp)
    ld a0, 80(sp)
    ld a1, 88(sp)
    ld a2, 96(sp)
#ifdef BAD_CONTEXT
    /* Corrupt the actual restored caller-saved register on timer returns. */
    csrr a3, scause
    bgez a3, 5f
    ld a3, 104(sp)
    addi a3, a3, 1
    j 6f
5:
    ld a3, 104(sp)
6:
#else
    ld a3, 104(sp)
#endif
    ld a4, 112(sp)
    ld a5, 120(sp)
    ld a6, 128(sp)
    ld a7, 136(sp)
    ld s2, 144(sp)
    ld s3, 152(sp)
    ld s4, 160(sp)
    ld s5, 168(sp)
    ld s6, 176(sp)
    ld s7, 184(sp)
    ld s8, 192(sp)
    ld s9, 200(sp)
    ld s10, 208(sp)
    ld s11, 216(sp)
    ld t3, 224(sp)
    ld t4, 232(sp)
    ld t5, 240(sp)
    ld t6, 248(sp)
    ld sp, 16(sp)
    .globl restore_user_return
restore_user_return:
    sret

restore_pc_failed:
    la a0, restore_pc_message
    call fail
    .section .rodata
restore_pc_message:
    .asciz "resume PC restore"
