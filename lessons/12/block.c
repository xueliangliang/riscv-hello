#include "block.h"
#include "uart.h"
#include "runtime.h"

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
static int poisoned;
static uint8_t dma_buffer[512] __attribute__((aligned(16)));
unsigned long block_reads, block_writes, block_flushes;
static unsigned config_generation;
static unsigned long clock_now(void)
{
    unsigned long value;
    __asm__ volatile("rdtime %0" : "=r"(value));
    return value;
}

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
    uart_puts("block: fail-closed code=");
    print_hex(error_code);
    uart_puts(" request-type=");
    print_hex(request_header.type);
    uart_puts(" status=");
    print_hex(request_status);
    uart_puts("\n");
    poisoned = 1;
    uint32_t current_status = read_register(VIRTIO_MMIO_STATUS);

    write_register(VIRTIO_MMIO_STATUS, current_status | DEVICE_STATUS_FAILED);
    return error_code;
}

int block_init(void)
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
        return -30;
    }

    write_register(VIRTIO_MMIO_STATUS, 0U);
    unsigned long reset_start = clock_now();
    while (read_register(VIRTIO_MMIO_STATUS) != 0) {
        if (clock_now() - reset_start > 10000000UL) {
            return fail_device(-20);
        }
    }
    write_register(VIRTIO_MMIO_STATUS, DEVICE_STATUS_ACKNOWLEDGE);
    write_register(VIRTIO_MMIO_STATUS,
                   DEVICE_STATUS_ACKNOWLEDGE | DEVICE_STATUS_DRIVER);

    write_register(VIRTIO_MMIO_DEVICE_FEATURES_SEL, 0U);
    uint32_t low_features = read_register(VIRTIO_MMIO_DEVICE_FEATURES);
#ifdef NO_FLUSH
    low_features &= ~(1U << 9); /* Explicit negative injection. */
#endif
    if ((low_features & (1U << 5)) || !(low_features & (1U << 9))) {
        return fail_device(-21);
    }
    write_register(VIRTIO_MMIO_DRIVER_FEATURES_SEL, 0U);
    write_register(VIRTIO_MMIO_DRIVER_FEATURES, 1U << 9);

    write_register(VIRTIO_MMIO_DEVICE_FEATURES_SEL, 1U);
    uint32_t device_features_high = read_register(VIRTIO_MMIO_DEVICE_FEATURES);
    if ((device_features_high & (1U << VIRTIO_FEATURE_VERSION_1)) == 0U) {
        return fail_device(-31);
    }

    write_register(VIRTIO_MMIO_DRIVER_FEATURES_SEL, 1U);
    write_register(VIRTIO_MMIO_DRIVER_FEATURES,
                   1U << VIRTIO_FEATURE_VERSION_1);

    uint32_t status = DEVICE_STATUS_ACKNOWLEDGE |
                      DEVICE_STATUS_DRIVER |
                      DEVICE_STATUS_FEATURES_OK;
    write_register(VIRTIO_MMIO_STATUS, status);
    if ((read_register(VIRTIO_MMIO_STATUS) & DEVICE_STATUS_FEATURES_OK) == 0U) {
        return fail_device(-32);
    }

    write_register(VIRTIO_MMIO_QUEUE_SEL, 0U);
    if (read_register(VIRTIO_MMIO_QUEUE_NUM_MAX) < VIRTQ_QUEUE_SIZE) {
        return fail_device(-33);
    }

    available_ring.flags = 1U; /* Polling, suppress queue completion IRQs. */
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
        return fail_device(-34);
    }

    config_generation = read_register(0xfc);
    uint32_t capacity_low = read_register(VIRTIO_MMIO_CONFIG);
    uint32_t capacity_high = read_register(VIRTIO_MMIO_CONFIG + 4U);
    device_capacity = ((uint64_t)capacity_high << 32) | capacity_low;
    last_used_index = used_ring.index;

    if (read_register(0xfc) != config_generation || device_capacity != 16384U) {
        return fail_device(-35);
    }

    return 0;
}

/* A source-level debugger checkpoint after validated device completion.
   It changes no protocol state and never lies about a failed completion. */
__attribute__((noinline)) void block_completion_observed(void)
{
    __asm__ volatile("" ::: "memory");
}

int block_request(unsigned type, uint64_t sector, void *buffer)
{
    if (poisoned || device_registers == NULL ||
        (type != 0 && type != 1 && type != 4) ||
        (type != 4 && (buffer == NULL || sector >= device_capacity))) {
        return -1;
    }

    if (read_register(0xfc) != config_generation ||
        read_register(VIRTIO_MMIO_STATUS) != 15 ||
        read_register(VIRTIO_MMIO_QUEUE_READY) != 1) {
        return fail_device(-22);
    }
    if (type == 1) {
        for (unsigned i = 0; i < 512; i++) {
            dma_buffer[i] = ((uint8_t *)buffer)[i];
        }
    }
    request_header.type = type;
    request_header.reserved = 0U;
    request_header.sector = sector;
    request_status = 0xffU;

    descriptors[0].address = (uint64_t)(uintptr_t)&request_header;
    descriptors[0].length = sizeof(request_header);
    descriptors[0].flags = VIRTQ_DESC_F_NEXT;
    descriptors[0].next = 1U;

    descriptors[1].address = (uint64_t)(uintptr_t)dma_buffer;
    descriptors[1].length = SECTOR_SIZE;
    descriptors[1].flags = VIRTQ_DESC_F_NEXT | (type == 0 ? VIRTQ_DESC_F_WRITE : 0);
    descriptors[1].next = 2U;

    descriptors[2].address = (uint64_t)(uintptr_t)&request_status;
    descriptors[2].length = sizeof(request_status);
    descriptors[2].flags = VIRTQ_DESC_F_WRITE;
    descriptors[2].next = 0U;

    if (type == 4) {
        /* Header -> status, with NO data descriptor. */
        descriptors[0].next = 2;
    }
    unsigned long start = clock_now();
    uint16_t available_index = available_ring.index;
    available_ring.ring[available_index % VIRTQ_QUEUE_SIZE] = 0U;
    __asm__ volatile("fence rw, rw" ::: "memory");
    available_ring.index = (uint16_t)(available_index + 1U);
    __asm__ volatile("fence rw, rw" ::: "memory");
    write_register(VIRTIO_MMIO_QUEUE_NOTIFY, 0U);

    uint16_t expected_used_index = last_used_index;
    while (used_ring.index == expected_used_index) {
        __asm__ volatile("fence r, rw" ::: "memory");
        if (clock_now() - start > 10000000UL) {
            return fail_device(-23);
        }
    }
    __asm__ volatile("fence rw, rw" ::: "memory");

    struct VirtqUsedElement completed =
        used_ring.ring[expected_used_index % VIRTQ_QUEUE_SIZE];
    last_used_index = (uint16_t)(expected_used_index + 1U);

    if (used_ring.index != last_used_index || completed.id != 0U || request_status != 0U ||
        completed.length != (type == 0 ? 513U : 1U) ||
        read_register(0xfc) != config_generation || read_register(VIRTIO_MMIO_STATUS) != 15 ||
        read_register(VIRTIO_MMIO_QUEUE_READY) != 1) {
        return fail_device(-24);
    }
    block_completion_observed();
    write_register(0x64, read_register(0x60));
    if (type == 0) {
        for (unsigned i = 0; i < 512; i++) {
            ((uint8_t *)buffer)[i] = dma_buffer[i];
        }
        block_reads++;
    } else if (type == 1) {
        block_writes++;
    } else {
        block_flushes++;
    }
    return 0;
}
