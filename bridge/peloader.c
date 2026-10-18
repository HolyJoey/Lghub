/*
 * Minimal loader for one x86-64 Windows DLL inside a Linux process — enough to call the DTS MicOpt
 * functions that logi_audio_dts_studio_capture_apo.dll exports. No Wine.
 *
 * Maps the sections, applies base relocations, and points every import at a thunk: functions we
 * implement get a real (ms_abi) implementation, anything else traps with its name so a missing one
 * is obvious instead of a mystery crash. The DSP entry points take caller-allocated memory, so the
 * DLL's C runtime start-up (DllMain) is not run.
 */
#define _GNU_SOURCE
#include "peloader.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

#define WINAPI __attribute__((ms_abi))

struct pe_image {
	uint8_t *base;
	size_t size;
	uint32_t export_dir, export_size;
};

static uint16_t rd16(const uint8_t *p) { return p[0] | p[1] << 8; }
static uint32_t rd32(const uint8_t *p) { return rd16(p) | (uint32_t)rd16(p + 2) << 16; }
static uint64_t rd64(const uint8_t *p) { return rd32(p) | (uint64_t)rd32(p + 4) << 32; }

/* --- the few Windows functions the DSP path may use ------------------------------------------- */

static uint32_t last_error;
static WINAPI uint32_t w_GetLastError(void) { return last_error; }
static WINAPI void w_SetLastError(uint32_t e) { last_error = e; }
static WINAPI void *w_GetProcessHeap(void) { return (void *)1; }
static WINAPI void *w_HeapAlloc(void *heap, uint32_t flags, size_t n)
{
	return flags & 0x8 ? calloc(1, n ? n : 1) : malloc(n ? n : 1); /* 0x8 = HEAP_ZERO_MEMORY */
}
static WINAPI int w_HeapFree(void *heap, uint32_t flags, void *p) { free(p); return 1; }
static WINAPI void *w_EncodePointer(void *p) { return p; }
static WINAPI void *w_DecodePointer(void *p) { return p; }
static WINAPI int w_IsProcessorFeaturePresent(uint32_t f) { return f == 10 || f == 17; } /* SSE2, NX */
static WINAPI void w_OutputDebugStringA(const char *s) { (void)s; }

static const struct { const char *name; void *fn; } implemented[] = {
	{"GetLastError", w_GetLastError}, {"SetLastError", w_SetLastError},
	{"GetProcessHeap", w_GetProcessHeap}, {"HeapAlloc", w_HeapAlloc}, {"HeapFree", w_HeapFree},
	{"EncodePointer", w_EncodePointer}, {"DecodePointer", w_DecodePointer},
	{"IsProcessorFeaturePresent", w_IsProcessorFeaturePresent},
	{"OutputDebugStringA", w_OutputDebugStringA},
};

/* --- traps for everything else ------------------------------------------------------------------ */

static void trap(const char *name)
{
	fprintf(stderr, "peloader: the DLL called %s, which is not implemented\n", name);
	abort();
}

/* mov rdi, imm64 (name); mov rax, imm64 (trap); jmp rax */
static void write_trap(uint8_t *at, const char *name)
{
	at[0] = 0x48; at[1] = 0xbf; memcpy(at + 2, &name, 8);
	at[10] = 0x48; at[11] = 0xb8; void *t = (void *)trap; memcpy(at + 12, &t, 8);
	at[20] = 0xff; at[21] = 0xe0;
}

static void *resolve(const char *name, uint8_t **trap_cursor)
{
	for (size_t i = 0; i < sizeof implemented / sizeof implemented[0]; i++)
		if (!strcmp(implemented[i].name, name)) return implemented[i].fn;
	uint8_t *t = *trap_cursor;
	write_trap(t, strdup(name));
	*trap_cursor += 32;
	return t;
}

/* --- loading ------------------------------------------------------------------------------------ */

pe_image *pe_load(const char *path)
{
	FILE *f = fopen(path, "rb");
	if (!f) return NULL;
	fseek(f, 0, SEEK_END);
	long len = ftell(f);
	fseek(f, 0, SEEK_SET);
	uint8_t *file = malloc(len);
	if (fread(file, 1, len, f) != (size_t)len) { fclose(f); free(file); return NULL; }
	fclose(f);

	uint32_t pe = rd32(file + 0x3c);
	if (len < 0x40 || memcmp(file + pe, "PE\0\0", 4) || rd16(file + pe + 4) != 0x8664) {
		free(file);
		return NULL;
	}
	uint16_t nsec = rd16(file + pe + 6), optsize = rd16(file + pe + 20);
	const uint8_t *opt = file + pe + 24;
	uint64_t image_base = rd64(opt + 24);
	uint32_t image_size = rd32(opt + 56), header_size = rd32(opt + 60);
	const uint8_t *dirs = opt + 112;
	const uint8_t *sections = opt + optsize;

	pe_image *img = calloc(1, sizeof *img);
	img->size = image_size;
	img->export_dir = rd32(dirs);
	img->export_size = rd32(dirs + 4);
	uint32_t rel = rd32(dirs + 8 * 5), rel_size = rd32(dirs + 8 * 5 + 4);
	uint32_t imp = rd32(dirs + 8 * 1);
	img->base = mmap(NULL, image_size, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	memcpy(img->base, file, header_size);
	for (int i = 0; i < nsec; i++) {
		const uint8_t *s = sections + 40 * i;
		uint32_t va = rd32(s + 12), raw_size = rd32(s + 16), raw = rd32(s + 20);
		if (raw_size) memcpy(img->base + va, file + raw, raw_size);
	}
	free(file);

	/* base relocations (only IMAGE_REL_BASED_DIR64 occurs in x64 images) */
	int64_t delta = (int64_t)(uintptr_t)img->base - (int64_t)image_base;
	for (uint32_t off = 0; delta && off < rel_size;) {
		const uint8_t *block = img->base + rel + off;
		uint32_t page = rd32(block), size = rd32(block + 4);
		for (uint32_t k = 8; k + 2 <= size; k += 2) {
			uint16_t e = rd16(block + k);
			if (e >> 12 == 10) *(uint64_t *)(img->base + page + (e & 0xfff)) += delta;
		}
		off += size;
	}

	/* imports */
	uint8_t *traps = mmap(NULL, 1 << 16, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	uint8_t *cursor = traps;
	for (const uint8_t *d = img->base + imp; imp && rd32(d + 12); d += 20) {
		uint32_t lookup = rd32(d) ? rd32(d) : rd32(d + 16), iat = rd32(d + 16);
		for (int k = 0;; k++) {
			uint64_t entry = rd64(img->base + lookup + 8 * k);
			if (!entry) break;
			char ordinal[32];
			const char *name = ordinal;
			if (entry >> 63) snprintf(ordinal, sizeof ordinal, "%s#%u", img->base + rd32(d + 12), (unsigned)(entry & 0xffff));
			else name = (const char *)img->base + (uint32_t)entry + 2;
			*(void **)(img->base + iat + 8 * k) = resolve(name, &cursor);
		}
	}

	if (getenv("PELOADER_DEBUG")) fprintf(stderr, "peloader: %s at %p\n", path, (void *)img->base);
	return img;
}

void *pe_symbol(pe_image *img, const char *name)
{
	const uint8_t *e = img->base + img->export_dir;
	uint32_t count = rd32(e + 24);
	const uint8_t *funcs = img->base + rd32(e + 28), *names = img->base + rd32(e + 32),
	              *ords = img->base + rd32(e + 36);
	for (uint32_t i = 0; i < count; i++) {
		if (!strcmp((const char *)img->base + rd32(names + 4 * i), name))
			return img->base + rd32(funcs + 4 * rd16(ords + 2 * i));
	}
	return NULL;
}

void *pe_rva(pe_image *img, unsigned rva)
{
	return rva < img->size ? img->base + rva : NULL;
}
