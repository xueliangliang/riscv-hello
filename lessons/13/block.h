#ifndef BLOCK_H
#define BLOCK_H
#include <stdint.h>
int block_init(void);
int block_request(unsigned type, uint64_t sector, void *buffer);
extern unsigned long block_reads, block_writes, block_flushes;
#endif
