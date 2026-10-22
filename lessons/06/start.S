/* Lesson06 owns this entry: disk-loaded, single hart, direct Sstc timer. */
    .option norvc
    .section .text.init, "ax", @progbits
    .globl _start
_start:
    la sp, __stack_top
    la t0, __bss_start
    la t1, __bss_end
1:
    bgeu t0, t1, 2f
    sb zero, 0(t0)
    addi t0, t0, 1
    j 1b
2:
    la t0, machine_trap
    csrw mtvec, t0
    la t0, machine_stack_top
    csrw mscratch, t0
    /* NAPOT RWX over all physical addresses: permission, NOT isolation. */
    li t0, -1
    csrw pmpaddr0, t0
    li t0, 0x1f
    csrw pmpcfg0, t0
    /* Delegate illegal instruction (2) and U ecall (8), not S ecall (9). */
    li t0, 0x104
    csrw medeleg, t0
    /* Sstc: M permits S time/stimecmp access, delegates STIP (not MTIP).
       No firmware timer service, SBI call, or M timer handler is involved. */
    li t0, 2
    csrw mcounteren, t0
    li t0, 0x8000000000000000
    csrw menvcfg, t0
    csrr t1, menvcfg
    bgez t1, machine_trap
    li t0, -1
    csrw 0x14d, t0
    li t0, 32
    csrw mideleg, t0
    csrw mie, zero
    csrw satp, zero
    sfence.vma
    la t0, supervisor_main
    csrw mepc, t0
    /* SXL=UXL=64, MPP=S, interrupts and MPRV cleared. */
    li t0, 0xa00000800
    csrw mstatus, t0
    mret

    .text
    .balign 4
machine_trap:
    csrrw sp, mscratch, sp
    call machine_fail
1:
    j 1b

    .globl enter_user
enter_user:
    la t0, supervisor_trap
    csrw stvec, t0
    la t0, __stack_top
    csrw sscratch, t0
    csrw sie, zero
    /* STIE remains masked until the START syscall; SIE stays zero in S. */
    li t0, 0x200000000
    csrw sstatus, t0
    li t0, 0x80400000
    csrw sepc, t0
    li sp, 0x80410000
    sret

    .bss
    .balign 16
machine_stack:
    .skip 4096
machine_stack_top:
