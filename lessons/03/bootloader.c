#include "boot_record.h"
#include "uart.h"
#include "virtio_blk.h"

#include <stdint.h>

static uint8_t boot_sector[DISK_SECTOR_SIZE] __attribute__((aligned(16)));

typedef void (*KernelEntry)(void);

static int fail(const char *message)
{
    uart_puts("ERROR: ");
    uart_puts(message);
    uart_puts("\r\n");
    return 1;
}

static int fail_virtio_initialization(int error_code)
{
    switch (error_code) {
    case VIRTIO_BLK_INIT_NO_DEVICE:
        return fail("no modern virtio-mmio block device was found.");
    case VIRTIO_BLK_INIT_NO_VERSION_1:
        return fail("the block device does not offer VIRTIO_F_VERSION_1.");
    case VIRTIO_BLK_INIT_FEATURES_REJECTED:
        return fail("the block device rejected the negotiated features.");
    case VIRTIO_BLK_INIT_QUEUE_TOO_SMALL:
        return fail("the block device's request queue is too small.");
    case VIRTIO_BLK_INIT_QUEUE_NOT_READY:
        return fail("the block device did not mark its request queue ready.");
    case VIRTIO_BLK_INIT_EMPTY_DEVICE:
        return fail("the block device reports zero capacity.");
    default:
        return fail("virtio block initialization failed.");
    }
}

static uint64_t sectors_for_size(uint64_t size_bytes)
{
    return (size_bytes + DISK_SECTOR_SIZE - 1U) / DISK_SECTOR_SIZE;
}

static int load_image(uint64_t first_sector,
                      uint64_t size_bytes,
                      uint64_t load_address)
{
    uint64_t sector_count = sectors_for_size(size_bytes);

    for (uint64_t sector_offset = 0; sector_offset < sector_count; ++sector_offset) {
        uint64_t destination_address = load_address +
                                      sector_offset * DISK_SECTOR_SIZE;
        void *destination = (void *)(uintptr_t)destination_address;
        if (virtio_blk_read_sector(first_sector + sector_offset,
                                   destination) != 0) {
            return -1;
        }
    }

    return 0;
}

static int boot_record_has_valid_magic(const struct BootRecord *record)
{
    static const char expected_magic[] = BOOT_RECORD_MAGIC;

    for (uint32_t index = 0; index < BOOT_RECORD_MAGIC_SIZE; ++index) {
        if (record->magic[index] != expected_magic[index]) {
            return 0;
        }
    }

    return 1;
}

int main(void)
{
    uart_puts("Lesson 03: M-mode bootloader started.\r\n");

    int virtio_status = virtio_blk_init();
    if (virtio_status != 0) {
        return fail_virtio_initialization(virtio_status);
    }

    if (virtio_blk_read_sector(BOOT_RECORD_LBA, boot_sector) != 0) {
        return fail("could not read the boot record.");
    }

    const struct BootRecord *record = (const struct BootRecord *)boot_sector;
    if (!boot_record_has_valid_magic(record)) {
        return fail("boot record magic does not match.");
    }

    if (record->version != BOOT_RECORD_VERSION ||
        record->header_size != BOOT_RECORD_HEADER_SIZE) {
        return fail("unsupported boot record version or header size.");
    }

    if (record->kernel_lba != KERNEL_IMAGE_LBA ||
        record->kernel_size_bytes == 0U ||
        record->kernel_size_bytes > MAX_IMAGE_BYTES ||
        record->load_address != KERNEL_LOAD_ADDRESS ||
        record->entry_address != KERNEL_LOAD_ADDRESS ||
        record->shell_size_bytes == 0U ||
        record->shell_size_bytes > MAX_IMAGE_BYTES ||
        record->shell_load_address != SHELL_LOAD_ADDRESS ||
        record->shell_entry_address != SHELL_LOAD_ADDRESS) {
        return fail("boot record fields are outside the lesson's load policy.");
    }

    uint64_t kernel_sector_count = sectors_for_size(record->kernel_size_bytes);
    uint64_t shell_sector_count = sectors_for_size(record->shell_size_bytes);
    if (record->shell_lba != record->kernel_lba + kernel_sector_count) {
        return fail("kernel and shell disk ranges are not contiguous.");
    }

    uint64_t capacity = virtio_blk_capacity_sectors();
    if (record->kernel_lba > capacity ||
        kernel_sector_count > capacity - record->kernel_lba ||
        record->shell_lba > capacity ||
        shell_sector_count > capacity - record->shell_lba) {
        return fail("kernel or shell image extends beyond the block device.");
    }

    uart_puts("Boot record validated; loading kernel and shell from disk.\r\n");
    if (load_image(record->kernel_lba,
                   record->kernel_size_bytes,
                   record->load_address) != 0) {
        return fail("virtio block read failed while loading the kernel.");
    }
    if (load_image(record->shell_lba,
                   record->shell_size_bytes,
                   record->shell_load_address) != 0) {
        return fail("virtio block read failed while loading the shell.");
    }

    __asm__ volatile("fence.i" ::: "memory");
    uart_puts("Bootloader: both images loaded; jumping to kernel at 0x80200000.\r\n");

    KernelEntry kernel_entry = (KernelEntry)(uintptr_t)record->entry_address;
    kernel_entry();

    return fail("kernel entry returned to the bootloader.");
}
