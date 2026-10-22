#include "virtio_blk.h"

#include <stddef.h>
#include <stdint.h>

#define VIRTIO_MMIO_BASE              0x10001000UL
#define VIRTIO_MMIO_SLOT_SIZE          0x1000UL
#define VIRTIO_MMIO_SLOT_COUNT         8U
#define VIRTIO_MMIO_MAGIC              0x000U
#define VIRTIO_MMIO_VERSION            0x004U
#define VIRTIO_MMIO_DEVICE_ID          0x008U
#define VIRTIO_MMIO_DEVICE_FEATURES    0x010U
#define VIRTIO_MMIO_DEVICE_FEATURES_SEL 0x014U
#define VIRTIO_MMIO_DRIVER_FEATURES    0x020U
#define VIRTIO_MMIO_DRIVER_FEATURES_SEL 0x024U
#define VIRTIO_MMIO_QUEUE_SEL           0x030U
#define VIRTIO_MMIO_QUEUE_NUM_MAX       0x034U
#define VIRTIO_MMIO_QUEUE_NUM           0x038U
#define VIRTIO_MMIO_QUEUE_READY         0x044U
#define VIRTIO_MMIO_QUEUE_NOTIFY        0x050U
#define VIRTIO_MMIO_STATUS              0x070U
#define VIRTIO_MMIO_QUEUE_DESC_LOW      0x080U
#define VIRTIO_MMIO_QUEUE_DESC_HIGH     0x084U
#define VIRTIO_MMIO_QUEUE_AVAIL_LOW     0x090U
#define VIRTIO_MMIO_QUEUE_AVAIL_HIGH    0x094U
#define VIRTIO_MMIO_QUEUE_USED_LOW      0x0a0U
#define VIRTIO_MMIO_QUEUE_USED_HIGH     0x0a4U
#define VIRTIO_MMIO_CONFIG              0x100U

#define VIRTIO_MAGIC_VALUE              0x74726976U
#define VIRTIO_VERSION_MODERN           2U
#define VIRTIO_DEVICE_BLOCK             2U
#define VIRTIO_FEATURE_VERSION_1        0U

#define DEVICE_STATUS_ACKNOWLEDGE       1U
#define DEVICE_STATUS_DRIVER            2U
#define DEVICE_STATUS_DRIVER_OK         4U
#define DEVICE_STATUS_FEATURES_OK       8U
#define DEVICE_STATUS_FAILED            128U

#define VIRTQ_QUEUE_SIZE                8U
#define VIRTQ_DESC_F_NEXT               1U
#define VIRTQ_DESC_F_WRITE              2U
#define VIRTIO_BLK_T_IN                 0U
#define SECTOR_SIZE                     512U

struct VirtqDescriptor {
    uint64_t address;
    uint32_t length;
    uint16_t flags;
    uint16_t next;
};

struct VirtqAvailable {
    volatile uint16_t flags;
    volatile uint16_t index;
    volatile uint16_t ring[VIRTQ_QUEUE_SIZE];
} __attribute__((aligned(2)));

struct VirtqUsedElement {
    volatile uint32_t id;
    volatile uint32_t length;
};

struct VirtqUsed {
    volatile uint16_t flags;
    volatile uint16_t index;
    struct VirtqUsedElement ring[VIRTQ_QUEUE_SIZE];
} __attribute__((aligned(4)));

struct VirtioBlockRequest {
    uint32_t type;
    uint32_t reserved;
    uint64_t sector;
} __attribute__((aligned(16)));

_Static_assert(sizeof(struct VirtqDescriptor) == 16U, "virtqueue descriptor size");
_Static_assert(sizeof(struct VirtioBlockRequest) == 16U, "block request header size");

static volatile uint32_t *device_registers;
static uint64_t device_capacity;
static uint16_t last_used_index;

static struct VirtqDescriptor descriptors[VIRTQ_QUEUE_SIZE] __attribute__((aligned(16)));
static volatile struct VirtqAvailable available_ring __attribute__((aligned(2)));
static volatile struct VirtqUsed used_ring __attribute__((aligned(4)));
static struct VirtioBlockRequest request_header __attribute__((aligned(16)));
static volatile uint8_t request_status;

static uint32_t read_register(uint32_t offset)
{
    return device_registers[offset / sizeof(uint32_t)];
}

static void write_register(uint32_t offset, uint32_t value)
{
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    device_registers[offset / sizeof(uint32_t)] = value;
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

static void write_queue_address(uint32_t low_register,
                                uint32_t high_register,
                                const void *address)
{
    uint64_t address_value = (uint64_t)(uintptr_t)address;

    write_register(low_register, (uint32_t)address_value);
    write_register(high_register, (uint32_t)(address_value >> 32));
}

static int fail_device(int error_code)
{
    uint32_t current_status = read_register(VIRTIO_MMIO_STATUS);

    write_register(VIRTIO_MMIO_STATUS, current_status | DEVICE_STATUS_FAILED);
    return error_code;
}

int virtio_blk_init(void)
{
    device_registers = NULL;
    device_capacity = 0U;

    for (uint32_t slot = 0; slot < VIRTIO_MMIO_SLOT_COUNT; ++slot) {
        uintptr_t address = VIRTIO_MMIO_BASE +
                            (uintptr_t)slot * VIRTIO_MMIO_SLOT_SIZE;
        volatile uint32_t *candidate = (volatile uint32_t *)address;

        if (candidate[VIRTIO_MMIO_MAGIC / 4U] == VIRTIO_MAGIC_VALUE &&
            candidate[VIRTIO_MMIO_VERSION / 4U] == VIRTIO_VERSION_MODERN &&
            candidate[VIRTIO_MMIO_DEVICE_ID / 4U] == VIRTIO_DEVICE_BLOCK) {
            device_registers = candidate;
            break;
        }
    }

    if (device_registers == NULL) {
        return VIRTIO_BLK_INIT_NO_DEVICE;
    }

    write_register(VIRTIO_MMIO_STATUS, 0U);
    write_register(VIRTIO_MMIO_STATUS, DEVICE_STATUS_ACKNOWLEDGE);
    write_register(VIRTIO_MMIO_STATUS,
                   DEVICE_STATUS_ACKNOWLEDGE | DEVICE_STATUS_DRIVER);

    write_register(VIRTIO_MMIO_DEVICE_FEATURES_SEL, 0U);
    (void)read_register(VIRTIO_MMIO_DEVICE_FEATURES);
    write_register(VIRTIO_MMIO_DRIVER_FEATURES_SEL, 0U);
    write_register(VIRTIO_MMIO_DRIVER_FEATURES, 0U);

    write_register(VIRTIO_MMIO_DEVICE_FEATURES_SEL, 1U);
    uint32_t device_features_high = read_register(VIRTIO_MMIO_DEVICE_FEATURES);
    if ((device_features_high & (1U << VIRTIO_FEATURE_VERSION_1)) == 0U) {
        return fail_device(VIRTIO_BLK_INIT_NO_VERSION_1);
    }

    write_register(VIRTIO_MMIO_DRIVER_FEATURES_SEL, 1U);
    write_register(VIRTIO_MMIO_DRIVER_FEATURES,
                   1U << VIRTIO_FEATURE_VERSION_1);

    uint32_t status = DEVICE_STATUS_ACKNOWLEDGE |
                      DEVICE_STATUS_DRIVER |
                      DEVICE_STATUS_FEATURES_OK;
    write_register(VIRTIO_MMIO_STATUS, status);
    if ((read_register(VIRTIO_MMIO_STATUS) & DEVICE_STATUS_FEATURES_OK) == 0U) {
        return fail_device(VIRTIO_BLK_INIT_FEATURES_REJECTED);
    }

    write_register(VIRTIO_MMIO_QUEUE_SEL, 0U);
    if (read_register(VIRTIO_MMIO_QUEUE_NUM_MAX) < VIRTQ_QUEUE_SIZE) {
        return fail_device(VIRTIO_BLK_INIT_QUEUE_TOO_SMALL);
    }

    available_ring.flags = 0U;
    available_ring.index = 0U;
    used_ring.flags = 0U;
    used_ring.index = 0U;
    for (uint32_t entry = 0; entry < VIRTQ_QUEUE_SIZE; ++entry) {
        available_ring.ring[entry] = 0U;
        used_ring.ring[entry].id = 0U;
        used_ring.ring[entry].length = 0U;
    }

    write_register(VIRTIO_MMIO_QUEUE_NUM, VIRTQ_QUEUE_SIZE);
    write_queue_address(VIRTIO_MMIO_QUEUE_DESC_LOW,
                        VIRTIO_MMIO_QUEUE_DESC_HIGH,
                        descriptors);
    write_queue_address(VIRTIO_MMIO_QUEUE_AVAIL_LOW,
                        VIRTIO_MMIO_QUEUE_AVAIL_HIGH,
                        (const void *)&available_ring);
    write_queue_address(VIRTIO_MMIO_QUEUE_USED_LOW,
                        VIRTIO_MMIO_QUEUE_USED_HIGH,
                        (const void *)&used_ring);
    write_register(VIRTIO_MMIO_QUEUE_READY, 1U);

    status |= DEVICE_STATUS_DRIVER_OK;
    write_register(VIRTIO_MMIO_STATUS, status);
    if (read_register(VIRTIO_MMIO_QUEUE_READY) != 1U) {
        return fail_device(VIRTIO_BLK_INIT_QUEUE_NOT_READY);
    }

    uint32_t capacity_low = read_register(VIRTIO_MMIO_CONFIG);
    uint32_t capacity_high = read_register(VIRTIO_MMIO_CONFIG + 4U);
    device_capacity = ((uint64_t)capacity_high << 32) | capacity_low;
    last_used_index = used_ring.index;

    if (device_capacity == 0U) {
        return fail_device(VIRTIO_BLK_INIT_EMPTY_DEVICE);
    }

    return 0;
}

uint64_t virtio_blk_capacity_sectors(void)
{
    return device_capacity;
}

int virtio_blk_read_sector(uint64_t sector, void *buffer)
{
    if (device_registers == NULL || buffer == NULL || sector >= device_capacity) {
        return -1;
    }

    request_header.type = VIRTIO_BLK_T_IN;
    request_header.reserved = 0U;
    request_header.sector = sector;
    request_status = 0xffU;

    descriptors[0].address = (uint64_t)(uintptr_t)&request_header;
    descriptors[0].length = sizeof(request_header);
    descriptors[0].flags = VIRTQ_DESC_F_NEXT;
    descriptors[0].next = 1U;

    descriptors[1].address = (uint64_t)(uintptr_t)buffer;
    descriptors[1].length = SECTOR_SIZE;
    descriptors[1].flags = VIRTQ_DESC_F_NEXT | VIRTQ_DESC_F_WRITE;
    descriptors[1].next = 2U;

    descriptors[2].address = (uint64_t)(uintptr_t)&request_status;
    descriptors[2].length = sizeof(request_status);
    descriptors[2].flags = VIRTQ_DESC_F_WRITE;
    descriptors[2].next = 0U;

    uint16_t available_index = available_ring.index;
    available_ring.ring[available_index % VIRTQ_QUEUE_SIZE] = 0U;
    __asm__ volatile("fence rw, rw" ::: "memory");
    available_ring.index = (uint16_t)(available_index + 1U);
    __asm__ volatile("fence rw, rw" ::: "memory");
    write_register(VIRTIO_MMIO_QUEUE_NOTIFY, 0U);

    uint16_t expected_used_index = last_used_index;
    while (used_ring.index == expected_used_index) {
        __asm__ volatile("fence r, rw" ::: "memory");
    }
    __asm__ volatile("fence rw, rw" ::: "memory");

    struct VirtqUsedElement completed =
        used_ring.ring[expected_used_index % VIRTQ_QUEUE_SIZE];
    last_used_index = (uint16_t)(expected_used_index + 1U);

    if (completed.id != 0U || request_status != 0U) {
        return -1;
    }

    return 0;
}
