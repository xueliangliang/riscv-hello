OUTPUT_ARCH(riscv)
ENTRY(_start)

PHDRS
{
    text PT_LOAD FLAGS(5);   /* R-X */
    rodata PT_LOAD FLAGS(4); /* R-- */
    data PT_LOAD FLAGS(6);   /* RW- */
}

SECTIONS
{
    . = 0x80200000;

    .text : ALIGN(16)
    {
        KEEP(*(.text.init))
        *(.text .text.*)
    } :text

    . = ALIGN(0x1000);
    .rodata : ALIGN(16)
    {
        *(.rodata .rodata.*)
        *(.srodata .srodata.*)
    } :rodata

    . = ALIGN(0x1000);
    .data : ALIGN(16)
    {
        __data_start = .;
        *(.data .data.*)
        *(.sdata .sdata.*)
        __data_end = .;
    } :data

    PROVIDE(__global_pointer$ = __data_start + 0x800);

    .bss (NOLOAD) : ALIGN(16)
    {
        __bss_start = .;
        *(.sbss .sbss.*)
        *(.bss .bss.*)
        *(COMMON)
        . = ALIGN(16);
        __bss_end = .;
    } :data

    /* Hart stacks are explicit arrays in start.S; no unused shared stack. */
    ASSERT(__bss_end < 0x80400000, "kernel BSS overlaps disk-loaded user image")

    /DISCARD/ :
    {
        *(.comment)
        *(.eh_frame*)
    }
}
