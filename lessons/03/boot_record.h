#ifndef LESSONS_03_BOOT_RECORD_H
#define LESSONS_03_BOOT_RECORD_H

#include <stdint.h>

#define BOOT_RECORD_MAGIC "RVKERN01"
#define BOOT_RECORD_MAGIC_SIZE 8U
#define BOOT_RECORD_VERSION 1U
#define BOOT_RECORD_HEADER_SIZE 80U
#define BOOT_RECORD_LBA 0U
#define KERNEL_IMAGE_LBA 1U
#define KERNEL_LOAD_ADDRESS 0x80200000UL
#define SHELL_LOAD_ADDRESS 0x80400000UL
#define MAX_IMAGE_BYTES (64U * 1024U)
#define DISK_SECTOR_SIZE 512U

struct BootRecord {
    char magic[BOOT_RECORD_MAGIC_SIZE];
    uint32_t version;
    uint32_t header_size;
    uint64_t kernel_lba;
    uint64_t kernel_size_bytes;
    uint64_t load_address;
    uint64_t entry_address;
    uint64_t shell_lba;
    uint64_t shell_size_bytes;
    uint64_t shell_load_address;
    uint64_t shell_entry_address;
} __attribute__((packed));

_Static_assert(sizeof(struct BootRecord) == BOOT_RECORD_HEADER_SIZE,
               "boot record header layout changed");

#endif
