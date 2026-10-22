#ifndef LESSONS_03_VIRTIO_BLK_H
#define LESSONS_03_VIRTIO_BLK_H

#include <stdint.h>

enum VirtioBlockInitError {
    VIRTIO_BLK_INIT_NO_DEVICE = -1,
    VIRTIO_BLK_INIT_NO_VERSION_1 = -2,
    VIRTIO_BLK_INIT_FEATURES_REJECTED = -3,
    VIRTIO_BLK_INIT_QUEUE_TOO_SMALL = -4,
    VIRTIO_BLK_INIT_QUEUE_NOT_READY = -5,
    VIRTIO_BLK_INIT_EMPTY_DEVICE = -6,
};

int virtio_blk_init(void);
int virtio_blk_read_sector(uint64_t sector, void *buffer);
uint64_t virtio_blk_capacity_sectors(void);

#endif
