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
        *(.bss .bss.* .sbss .sbss.* COMMON)
        . = ALIGN(16);
        __user_bss_end = .;
    } :data
    ASSERT(. <= 0x80408000, "user image overlaps reserved heap")
    .heap 0x80408000 (NOLOAD) : {
        __heap_start = .;
        . += 0x4000;
        __heap_end = .;
    } :data
    .stack 0x8040c000 (NOLOAD) : {
        . += 0x4000;
        __user_stack_top = .;
    } :data
    /DISCARD/ :
    {
        *(.comment .riscv.attributes .eh_frame*)
    }
}
