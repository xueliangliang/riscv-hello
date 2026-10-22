    .option norvc
    .section .text.init, "ax", @progbits
    .globl user_entry
user_entry:
    j user_start
    .org 0x10
    /* C call ABI (number, arg0, arg1) -> syscall ABI (a7, a0, a1). */
    .globl syscall
syscall:
    mv a7, a0
    mv a0, a1
    mv a1, a2
    .globl syscall_ecall
syscall_ecall:
    ecall
    ret
    .org 0x30
    .globl user_bad_trap
user_bad_trap:
    csrr t0, sstatus
    ret
    .text
user_start:
    /* Flat disk loading does not materialize ELF NOLOAD sections. */
    la t0, __user_bss_start
    la t1, __user_bss_end
1:
    bgeu t0, t1, 2f
    sb zero, 0(t0)
    addi t0, t0, 1
    j 1b
2:
    call user_main
    call mini_exit
3:
    j 3b
