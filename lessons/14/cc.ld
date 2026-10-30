OUTPUT_ARCH(riscv)
ENTRY(app_entry)
PHDRS { text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
SECTIONS
{
    . = 0x80500000;
    .text : { KEEP(*(.text.init)) *(.text .text.*) } :text
    __code_end = .;
    .rodata : { *(.rodata .rodata.* .srodata*) } :text
    . = ALIGN(16);
    .data : { *(.data .data.* .sdata*) . = ALIGN(16); BYTE(0); . = ALIGN(16); } :data
    __payload_end = .;
    .bss (NOLOAD) : {
        __compiler_bss_start = .;
        *(.bss .bss.* .sbss* COMMON)
        . = ALIGN(16);
    } :data
    __memory_end = .;
    __compiler_bss_end = .;
    ASSERT(__payload_end - 0x80500000 + 48 <= 65536, "compiler file bound")
    ASSERT(. <= 0x80600000, "application exceeds reserved memory")
    /DISCARD/ : { *(.comment .eh_frame*) }
}
