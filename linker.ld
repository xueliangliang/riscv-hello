OUTPUT_ARCH(riscv)
ENTRY(_start)

SECTIONS
{
    /* With -bios none, QEMU virt's generated reset stub jumps to 0x80000000. */
    . = 0x80000000;

    .text : ALIGN(4)
    {
        KEEP(*(.text.init))
        *(.text .text.*)
    }

    .rodata : ALIGN(8)
    {
        *(.rodata .rodata.*)
        *(.srodata .srodata.*)
    }

    /DISCARD/ :
    {
        *(.comment)
        *(.riscv.attributes)
    }
}
