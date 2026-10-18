#ifndef PELOADER_H
#define PELOADER_H

typedef struct pe_image pe_image;

/* Generic function pointer; cast to the real __attribute__((ms_abi)) type before calling. */
typedef void (*pe_fn)(void);

/* Loads an x86-64 Windows DLL into this process. Returns NULL if it isn't one. */
pe_image *pe_load(const char *path);

/* Address of the image's byte at a relative virtual address. */
void *pe_rva(pe_image *img, unsigned rva);

/* An exported function, or NULL. */
pe_fn pe_function(pe_image *img, const char *name);

#endif
