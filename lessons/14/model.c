/* Actual-C storage model. A successful FLUSH persists every preceding WRITE.
 * Atomic sector writes can survive even if the device reports an error.
 * Tests explicitly choose either legal outcome; this is not a journal rewrite. */
#include "block.h"
#include "fs.h"
#include "journal.h"
#include <string.h>
#include <setjmp.h>
#include <stdint.h>
#define BYTES (8U * 1024U * 1024U)
static unsigned char volatile_disk[BYTES];
static unsigned char durable_disk[BYTES];
static jmp_buf escape;
static unsigned crash_phase;
static unsigned crash_index;
static int fault_type = -1;
static long fault_sector = -1;
static unsigned fault_occurrence;
static int persist_error;
/* Bounded evidence must never silently discard a late write. The host checks
 * overflow after every native call, not only when inspecting a successful run. */
#define TRACE_CAPACITY 262144U
static unsigned trace_count;
static unsigned trace_overflow;
static unsigned trace_type[TRACE_CAPACITY];
static unsigned trace_sector[TRACE_CAPACITY];
unsigned long block_reads, block_writes, block_flushes;
extern long workload(unsigned operation);
void uart_puts(const char *s)
{
    (void)s;
}
void print_hex(uint64_t value)
{
    (void)value;
}
int block_init(void)
{
    return 0;
}
void model_load(const void *bytes)
{
    memcpy(volatile_disk, bytes, BYTES);
    memcpy(durable_disk, bytes, BYTES);
    crash_phase = 0;
    fault_type = -1;
    trace_count = 0;
    trace_overflow = 0;
}
void model_disk(void *bytes)
{
    memcpy(bytes, durable_disk, BYTES);
}
void model_cut(void)
{
    memcpy(volatile_disk, durable_disk, BYTES);
    crash_phase = 0;
    fault_type = -1;
}
void model_crash(unsigned phase, unsigned index)
{
    crash_phase = phase;
    crash_index = index;
}
void model_fault(int type, long sector, unsigned occurrence, int persisted)
{
    fault_type = type;
    fault_sector = sector;
    fault_occurrence = occurrence;
    persist_error = persisted;
}
unsigned model_trace_count(void)
{
    return trace_count;
}
unsigned model_trace_overflow(void)
{
    return trace_overflow;
}
unsigned model_trace_capacity(void)
{
    return TRACE_CAPACITY;
}
unsigned model_trace(unsigned index, int sector)
{
    if (index >= trace_count) {
        return 0xffffffffU;
    }
    return sector ? trace_sector[index] : trace_type[index];
}
int block_request(unsigned type, uint64_t sector, void *buffer)
{
    if (trace_count < TRACE_CAPACITY) {
        trace_type[trace_count] = type;
        trace_sector[trace_count] = sector;
        trace_count++;
    } else {
        trace_overflow = 1;
    }
    if ((type != 4 && sector >= 16384) || (type != 0 && type != 1 && type != 4)) {
        return -1;
    }
    int fault = 0;
    if ((int)type == fault_type && (fault_sector < 0 || sector == (uint64_t)fault_sector)) {
        if (--fault_occurrence == 0) {
            fault = 1;
            fault_type = -1;
        }
    }
    if (type == 0) {
        block_reads++;
        if (!fault) {
            memcpy(buffer, volatile_disk + sector * 512, 512);
        }
    } else if (type == 1) {
        block_writes++;
        if (!fault || persist_error) {
            memcpy(volatile_disk + sector * 512, buffer, 512);
        }
        if (fault && persist_error) {
            memcpy(durable_disk + sector * 512, buffer, 512);
        }
    } else {
        block_flushes++;
        if (!fault || persist_error) {
            memcpy(durable_disk, volatile_disk, BYTES);
        }
    }
    return fault ? -1 : 0;
}
void journal_hook(unsigned phase, unsigned index)
{
    if (crash_phase == phase && (!crash_index || crash_index == index)) {
        longjmp(escape, 1);
    }
}
long model_run(unsigned operation)
{
    if (setjmp(escape)) {
        model_cut();
        return -99;
    }
    if (operation == 0) {
        return fs_mount();
    }
    return workload(operation);
}
