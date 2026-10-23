/* Both harts reach here only after disk loading. Hart1 remains in boot.S
   until hart0 has also cleared shared BSS and initialized the process table. */
    .option norvc
    .section .text.init, "ax", @progbits
    .globl _start
_start:
    csrr a0, mhartid
    bnez a0, 2f
    la t0, __bss_start
    la t1, __bss_end
1:
    bgeu t0, t1, 2f
    sb zero, 0(t0)
    addi t0, t0, 1
    j 1b
2:
    /* Two 16KiB trusted S stacks; last 16 bytes hold immutable Hart*. */
    la sp, supervisor_stacks
    addi t0, a0, 1
    slli t0, t0, 14
    add sp, sp, t0
    addi sp, sp, -16
    mv a1, sp
    la t0, machine_trap
    csrw mtvec, t0
    la t0, machine_stacks
    addi t1, a0, 1
    slli t1, t1, 12
    add t0, t0, t1
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
    csrw scounteren, zero
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

    .bss
    .balign 16
machine_stacks:
    .skip 8192
    .balign 16
    .globl supervisor_stacks
supervisor_stacks:
    .skip 32768
