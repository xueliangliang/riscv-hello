#ifndef REDO12_H
#define REDO12_H
#define J_CAPACITY 1024U
#define J_HEADER 12288U
#define J_DESC (J_HEADER + 1U)
#define J_IMAGES (J_DESC + 16U)
#define J_IO (-14)
#define J_LIMIT (-17)
unsigned journal_crc(const void *bytes, unsigned length);
int journal_identity(const unsigned char *sector);
int journal_recover(void);
int journal_begin(void);
void journal_abort(void);
int journal_io(unsigned type, unsigned sector, void *buffer);
int journal_commit(void);
int journal_error(void);
/* Weak production no-op. Test backends can interrupt only an armed operation.
 * Phases: 1 before log flush; 2 after; 3 before commit flush; 4 after;
 * 5 home prefix; 6 home durable; 7 clear written; 8 clear durable;
 * 9 replay prefix. No hook changes ordering or error classification. */
void journal_hook(unsigned phase, unsigned index);
#endif
