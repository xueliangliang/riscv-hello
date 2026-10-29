/* Native transport shim, not a substitute for the real QEMU IOERR tests.
 * Include the actual driver with ONLY time/fence/MMIO access substituted.
 * Keep the reset/negotiation/request algorithm and all DMA objects intact. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
static uint32_t test_read(uint32_t offset);
static void test_write(uint32_t offset, uint32_t value);
static unsigned long test_clock(void);
#include "block-reset-driver.c"

static int mode;
static int acknowledged;
static int init_finished;
static unsigned long ticks;
static unsigned low_selected;
static unsigned char saved_descriptors[sizeof(descriptors)];
static unsigned char saved_available[sizeof(available_ring)];
static unsigned char saved_used[sizeof(used_ring)];
static unsigned char saved_header[sizeof(request_header)];
static unsigned char saved_dma[sizeof(dma_buffer)];
static unsigned char saved_status;

void uart_puts(const char *text) { (void)text; }
void print_hex(uint64_t value) { (void)value; }

static void unchanged(void)
{
    assert(memcmp(saved_descriptors, descriptors, sizeof(descriptors)) == 0);
    assert(memcmp(saved_available, (const void *)&available_ring, sizeof(available_ring)) == 0);
    assert(memcmp(saved_used, (const void *)&used_ring, sizeof(used_ring)) == 0);
    assert(memcmp(saved_header, &request_header, sizeof(request_header)) == 0);
    assert(memcmp(saved_dma, dma_buffer, sizeof(dma_buffer)) == 0);
    assert(saved_status == request_status);
}
static unsigned long test_clock(void)
{
    ticks += 10000001UL;
    return ticks;
}
static uint32_t test_read(uint32_t offset)
{
    if (!init_finished) {
        assert(poisoned == 1);
    }
    if (!acknowledged) {
        assert(poisoned == 1);
        unchanged();
    }
    if (offset == VIRTIO_MMIO_STATUS && device_registers[offset / 4] == 0) {
        acknowledged = 1;
    }
    if (offset == VIRTIO_MMIO_DEVICE_FEATURES) {
        return low_selected ? 1U : mode == 2 ? 0U : 1U << 9;
    }
    if (offset == VIRTIO_MMIO_QUEUE_NUM_MAX) {
        return 8;
    }
    if (offset == VIRTIO_MMIO_CONFIG) {
        return mode == 4 ? 0 : 16384;
    }
    return device_registers[offset / 4];
}
static void test_write(uint32_t offset, uint32_t value)
{
    if (!init_finished) {
        assert(poisoned == 1);
    }
    if (!acknowledged) {
        assert(poisoned == 1);
        unchanged();
    }
    if (offset == VIRTIO_MMIO_DEVICE_FEATURES_SEL) {
        low_selected = value;
    }
    if (offset == VIRTIO_MMIO_STATUS && value == 0 && mode == 1) {
        return; /* No reset ACK: old DMA ownership must remain quarantined. */
    }
    if (offset == VIRTIO_MMIO_QUEUE_READY && mode == 3) {
        return;
    }
    device_registers[offset / 4] = value;
    if (offset == VIRTIO_MMIO_QUEUE_NOTIFY) {
        assert(acknowledged && !poisoned);
        request_status = 0;
        used_ring.ring[last_used_index % VIRTQ_QUEUE_SIZE].id = 0;
        used_ring.ring[last_used_index % VIRTQ_QUEUE_SIZE].length = 1;
        used_ring.index++;
    }
}
static void setup(int next)
{
    mode = next;
    acknowledged = 0;
    init_finished = 0;
    ticks = 0;
    low_selected = 0;
    volatile uint32_t *registers = (volatile uint32_t *)VIRTIO_MMIO_BASE;
    memset((void *)registers, 0, VIRTIO_MMIO_SLOT_COUNT * VIRTIO_MMIO_SLOT_SIZE);
    registers[VIRTIO_MMIO_MAGIC / 4] = mode == 5 ? 0 : VIRTIO_MAGIC_VALUE;
    registers[VIRTIO_MMIO_VERSION / 4] = VIRTIO_VERSION_MODERN;
    registers[VIRTIO_MMIO_DEVICE_ID / 4] = VIRTIO_DEVICE_BLOCK;
    registers[VIRTIO_MMIO_STATUS / 4] = 15;
    memset(descriptors, 0xa5, sizeof(descriptors));
    memset((void *)&available_ring, 0xb6, sizeof(available_ring));
    memset((void *)&used_ring, 0xc7, sizeof(used_ring));
    memset(&request_header, 0xd8, sizeof(request_header));
    memset(dma_buffer, 0xe9, sizeof(dma_buffer));
    request_status = 0xff;
    memcpy(saved_descriptors, descriptors, sizeof(descriptors));
    memcpy(saved_available, (const void *)&available_ring, sizeof(available_ring));
    memcpy(saved_used, (const void *)&used_ring, sizeof(used_ring));
    memcpy(saved_header, &request_header, sizeof(request_header));
    memcpy(saved_dma, dma_buffer, sizeof(dma_buffer));
    saved_status = request_status;
    poisoned = 0; /* A previously healthy queue must also be gated during init. */
}
int main(void)
{
    void *mapped = mmap((void *)VIRTIO_MMIO_BASE,
                        VIRTIO_MMIO_SLOT_COUNT * VIRTIO_MMIO_SLOT_SIZE,
                        PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE,
                        -1, 0);
    assert(mapped == (void *)VIRTIO_MMIO_BASE);
    const int errors[] = {0, -20, -21, -34, -35, -30};
    for (int scenario = 1; scenario <= 5; scenario++) {
        setup(scenario);
        assert(block_init() == errors[scenario]);
        assert(poisoned && block_request(4, 0, 0) < 0);
        if (scenario == 1 || scenario == 5) {
            assert(!acknowledged);
            unchanged();
        }
        printf("PASS block quarantine scenario=%d error=%d\n", scenario, errors[scenario]);
    }
    setup(0);
    assert(block_init() == 0 && acknowledged && !poisoned);
    init_finished = 1;
    assert(block_request(4, 0, 0) == 0);
    puts("PASS confirmed reset plus complete reinit releases quarantine and submits FLUSH");
    return 0;
}
