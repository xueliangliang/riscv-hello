    .option norvc
    .section .text.init, "ax", @progbits
    .globl user_entry
user_entry:
    j user_main
    .org 0x10
    .globl user_ecall
user_ecall:
    ecall
    ret
    .org 0x20
    .globl user_csr
user_csr:
#ifdef BAD_CAUSE
    ecall
#elif defined(BAD_PC)
    nop
    csrr t0, sstatus
#else
    csrr t0, sstatus
#endif
    ret
    .org 0x30
    .globl user_exit
user_exit:
    ecall
    j user_exit
    .text
user_main:
    li t0, 0x123
    li t1, 0x456
    li s1, 0x789
    li a3, 0xabc
    li a7, 0
    call user_ecall
    li t2, 42
    bne a0, t2, bad
    li t2, 0x123
    bne t0, t2, bad
    li t2, 0x456
    bne t1, t2, bad
    li t2, 0x789
    bne s1, t2, bad
    li t2, 0xabc
    bne a3, t2, bad
    call user_csr
    li a0, 0
    li a7, 1
    j user_exit
bad:
    li a0, 1
    li a7, 1
    j user_exit
