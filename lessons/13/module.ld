OUTPUT_ARCH(riscv)
ENTRY(math_ceil)
SECTIONS
{
    . = 128;
    .text : { *(.text .text.*) }
    .forbidden : { *(.data* .rodata* .bss* .sdata* .sbss* .got* .tdata* .tbss*) }
    ASSERT(SIZEOF(.forbidden) == 0, "module must be self-contained text only")
    ASSERT(. <= 4096, "module exceeds bank")
    /DISCARD/ : { *(.comment .eh_frame*) }
}
