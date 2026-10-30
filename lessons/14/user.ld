OUTPUT_ARCH(riscv)
ENTRY(user_entry)
PHDRS
{
    text PT_LOAD FLAGS(5);
    rodata PT_LOAD FLAGS(4);
    data PT_LOAD FLAGS(6);
}
SECTIONS
{
    . = 0x80400000;
    .text : {
        KEEP(*(.text.init))
        *(.text .text.*)
    } :text
    . = ALIGN(0x1000);
    .rodata :
    {
        *(.rodata .rodata.* .srodata .srodata.*)
    } :rodata
    . = ALIGN(0x1000);
    .data :
    {
        *(.data .data.* .sdata .sdata.*)
    } :data
    .bss (NOLOAD) : ALIGN(16) {
        __user_bss_start = .;
        . = ALIGN(16);
        __user_bss_end = .;
    } :data
    ASSERT(. <= 0x80407000, "user text/data/BSS overlaps per-instance data")
    .taskdata 0x80407000 (NOLOAD) : {
        . += 8 * 256;
        __taskdata_end = .;
    } :data
    ASSERT(__taskdata_end <= 0x80408000, "per-instance data overlaps stacks")
    .stacks 0x80408000 (NOLOAD) : {
        . += 8 * 4096;
        __user_stacks_end = .;
    } :data
    ASSERT(__user_stacks_end == 0x80410000, "eight independent stack budget")
    .appstack 0x80410000 (NOLOAD) : {
        . += 65536;
        __app_stack_end = .;
    } :data
    .paste 0x80420000 (NOLOAD) : {
        *(.paste)
        . = ALIGN(16);
        *(.bss .bss.* .sbss .sbss.* COMMON)
        . = ALIGN(16);
        __paste_end = .;
    } :data
    ASSERT(__app_stack_end == 0x80420000, "ABI2 stack budget")
    ASSERT(__paste_end <= 0x80424000, "shell raw workspace budget")
    /DISCARD/ : { *(.comment .riscv.attributes .eh_frame*) }
}
