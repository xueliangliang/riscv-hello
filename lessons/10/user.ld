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
    /DISCARD/ : { *(.comment .riscv.attributes .eh_frame*) }
}
