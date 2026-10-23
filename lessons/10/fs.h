#ifndef FLAT_FS_H
#define FLAT_FS_H
#define FS_OPEN 17
#define FS_READ 18
#define FS_WRITE 19
#define FS_FLUSH 20
#define FS_CLOSE 21
#define FS_REMOVE 22
#define FS_LIST 23
#define FS_INFO 24
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
#define FS_BYTES 4096
#define FS_FILES 16
#define FS_HANDLES 4
int fs_mount(void);
long fs_open(const char *name, unsigned mode);
long fs_read(long handle, void *buffer, unsigned count);
long fs_write(long handle, const void *buffer, unsigned count);
long fs_flush(long handle);
long fs_close(long handle);
long fs_remove(const char *name);
int fs_list(void);
void fs_info(void);
int fs_sync(void);
#endif
