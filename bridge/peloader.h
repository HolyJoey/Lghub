#ifndef PELOADER_H
#define PELOADER_H

typedef struct pe_image pe_image;

/* Loads an x86-64 Windows DLL into this process. Returns NULL if it isn't one. */
pe_image *pe_load(const char *path);

/* Address of the image's byte at a relative virtual address. */
void *pe_rva(pe_image *img, unsigned rva);

/* Address of an exported function, or NULL. Call it through an __attribute__((ms_abi)) pointer. */
void *pe_symbol(pe_image *img, const char *name);

#endif
