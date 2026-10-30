OUTPUT_ARCH(riscv)
ENTRY(rt_guard)
PHDRS { text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
SECTIONS
{
    . = 0x80500000;
    .metadata : { . += 256; } :text
    __functions_begin = .;
    .text : { *(.text .text.*) } :text
    __functions_end = .;
    .rodata : { *(.rodata .rodata.* .srodata*) } :text
    .data : { *(.data .data.* .sdata*) } :data
    __runtime_payload_end = .;
    ASSERT(. <= 0x80505000, "runtime exceeds20KiB prefix")
    . = 0x80510000;
    __runtime_bss_begin = .;
    .bss (NOLOAD) : { *(.bss .bss.* .sbss* COMMON) . = ALIGN(16); } :data
    __runtime_bss_end = .;
    ASSERT(. <= 0x80600000, "runtime BSS exceeds1MiB arena")
    /DISCARD/ : { *(.comment .eh_frame*) }
}
