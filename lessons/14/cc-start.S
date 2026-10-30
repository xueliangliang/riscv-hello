.section .text.init
.global app_entry
app_entry:
    call cc_main
    li a0, 99
    li a7, 4
    ecall
1:
    j 1b
