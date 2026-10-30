.section .text.init
.globl app_entry
app_entry:
    call app_main
    li a7, 4
    ecall
1:  j 1b
