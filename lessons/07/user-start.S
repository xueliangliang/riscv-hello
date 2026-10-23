    .option norvc
    .section .text.init, "ax", @progbits
    .globl user_entry
user_entry:
    j user_main
    .text
    .globl spin_worker
spin_worker:
    li a3, 0x12345
    li s2, 0x54321
    li s0, 0
    li t0, 0x13579
    sd t0, -8(sp)
    .globl spin_loop
spin_loop:
    addi s0, s0, 1
    sd s0, 0(a2)
    j spin_loop
    .globl spin_loop_end
spin_loop_end:
