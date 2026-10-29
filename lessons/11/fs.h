#ifndef BPT_FS_H
#define BPT_FS_H
#include <stdint.h>
#define FS_OPEN 17
#define FS_READ 18
#define FS_WRITE 19
#define FS_FLUSH 20
#define FS_CLOSE 21
#define FS_REMOVE 22
#define FS_LIST 23
#define FS_INFO 24
#define FS_APPEND 25
#define FS_SEEK 26
#define FS_TRUNCATE 27
#define FS_LIST_PAGE 28
#define FS_DEFRAG 29
#define F_ARG (-4L)
#define F_MISSING (-10L)
#define F_FULL (-11L)
#define F_HANDLE (-12L)
#define F_BUSY (-13L)
#define F_IO (-14L)
#define F_MODE (-15L)
#define F_GENERATION (-16L)
#define FS_EXISTING 0
#define FS_REPLACE 1
#define FS_RW 2
#define FS_BYTES 65536
#define FS_FILES 512
#define FS_HANDLES 4
struct FileEntry {
    char name[32];
    uint32_t size;
};
struct ListCursor {
    uint32_t epoch;
    uint32_t index;
};
int fs_mount(void);
int fs_sync(void);
long fs_open(const char *name, unsigned mode);
long fs_read(long handle, void *buffer, unsigned count);
long fs_write(long handle, const void *buffer, unsigned count);
long fs_append(long handle, const void *buffer, unsigned count);
long fs_seek(long handle, unsigned offset);
long fs_truncate(long handle, unsigned size);
long fs_flush(long handle);
long fs_close(long handle);
long fs_remove(const char *name);
long fs_list_page(struct FileEntry *entries, unsigned capacity, struct ListCursor *cursor);
long fs_defrag(void);
void fs_info(void);
#endif
