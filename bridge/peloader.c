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

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

#define WINAPI __attribute__((ms_abi))
#define DIR_EXPORT 0                /* byte offsets of data directory entries */
#define DIR_IMPORT 8
#define DIR_BASERELOC 40
#define TRAP_SIZE 32
#define TRAP_AREA (1 << 16)

struct pe_image {
	uint8_t *base;
	size_t size;
	uint32_t export_dir, export_size;
};

static uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }
static uint32_t rd32(const uint8_t *p) { return rd16(p) | (uint32_t)rd16(p + 2) << 16; }
static uint64_t rd64(const uint8_t *p) { return rd32(p) | (uint64_t)rd32(p + 4) << 32; }

/* --- the few Windows functions the DSP path may use ------------------------------------------- */

static uint32_t last_error;
static WINAPI uint32_t w_GetLastError(void) { return last_error; }
static WINAPI void w_SetLastError(uint32_t e) { last_error = e; }
static WINAPI void *w_GetProcessHeap(void) { return (void *)1; }
static WINAPI void *w_HeapAlloc(void *heap, uint32_t flags, size_t n)
{
	(void)heap;
	return flags & 0x8 ? calloc(1, n ? n : 1) : malloc(n ? n : 1); /* 0x8 = HEAP_ZERO_MEMORY */
}
static WINAPI int w_HeapFree(void *heap, uint32_t flags, void *p)
{
	(void)heap;
	(void)flags;
	free(p);
	return 1;
}
static WINAPI void *w_EncodePointer(void *p) { return p; }
static WINAPI void *w_DecodePointer(void *p) { return p; }
static WINAPI int w_IsProcessorFeaturePresent(uint32_t f) { return f == 10 || f == 17; } /* SSE2, NX */
static WINAPI void w_OutputDebugStringA(const char *s) { (void)s; }

/* the C runtime's maths (the Conexant EQ design uses them; same calling convention for doubles) */
static WINAPI double w_sin(double x) { return sin(x); }
static WINAPI double w_cos(double x) { return cos(x); }
static WINAPI double w_sinh(double x) { return sinh(x); }
static WINAPI double w_sqrt(double x) { return sqrt(x); }
static WINAPI double w_pow(double x, double y) { return pow(x, y); }
static WINAPI double w_log(double x) { return log(x); }
static WINAPI double w_log10(double x) { return log10(x); }
static WINAPI double w_exp(double x) { return exp(x); }
static WINAPI double w_acos(double x) { return acos(x); }
static WINAPI double w_atan(double x) { return atan(x); }
static WINAPI double w_atan2(double y, double x) { return atan2(y, x); }
static WINAPI float w_sinf(float x) { return sinf(x); }
static WINAPI float w_cosf(float x) { return cosf(x); }
static WINAPI float w_sqrtf(float x) { return sqrtf(x); }
static WINAPI float w_powf(float x, float y) { return powf(x, y); }
static WINAPI float w_log10f(float x) { return log10f(x); }
static WINAPI float w_acosf(float x) { return acosf(x); }
static WINAPI void *w_memset(void *d, int c, size_t n) { return memset(d, c, n); }
static WINAPI void *w_memcpy(void *d, const void *s, size_t n) { return memcpy(d, s, n); }
static WINAPI void *w_memmove(void *d, const void *s, size_t n) { return memmove(d, s, n); }
static WINAPI int w_memcmp(const void *a, const void *b, size_t n) { return memcmp(a, b, n); }

static const struct { const char *name; pe_fn fn; } implemented[] = {
	{"GetLastError", (pe_fn)w_GetLastError}, {"SetLastError", (pe_fn)w_SetLastError},
	{"GetProcessHeap", (pe_fn)w_GetProcessHeap}, {"HeapAlloc", (pe_fn)w_HeapAlloc},
	{"HeapFree", (pe_fn)w_HeapFree}, {"EncodePointer", (pe_fn)w_EncodePointer},
	{"DecodePointer", (pe_fn)w_DecodePointer},
	{"IsProcessorFeaturePresent", (pe_fn)w_IsProcessorFeaturePresent},
	{"OutputDebugStringA", (pe_fn)w_OutputDebugStringA},
	{"sin", (pe_fn)w_sin}, {"cos", (pe_fn)w_cos}, {"sinh", (pe_fn)w_sinh}, {"sqrt", (pe_fn)w_sqrt},
	{"pow", (pe_fn)w_pow}, {"log", (pe_fn)w_log}, {"log10", (pe_fn)w_log10}, {"exp", (pe_fn)w_exp},
	{"acos", (pe_fn)w_acos}, {"atan", (pe_fn)w_atan}, {"atan2", (pe_fn)w_atan2}, {"sinf", (pe_fn)w_sinf},
	{"cosf", (pe_fn)w_cosf}, {"sqrtf", (pe_fn)w_sqrtf}, {"powf", (pe_fn)w_powf}, {"log10f", (pe_fn)w_log10f},
	{"acosf", (pe_fn)w_acosf}, {"memset", (pe_fn)w_memset}, {"memcpy", (pe_fn)w_memcpy},
	{"memmove", (pe_fn)w_memmove}, {"memcmp", (pe_fn)w_memcmp},
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
	void (*handler)(const char *) = trap;
	at[0] = 0x48; at[1] = 0xbf; memcpy(at + 2, (const void *)&name, 8);
	at[10] = 0x48; at[11] = 0xb8; memcpy(at + 12, (const void *)&handler, 8);
	at[20] = 0xff; at[21] = 0xe0;
}

/* Writes the address for import `name` into the IAT slot. Returns -1 if out of trap space. */
static int resolve(uint8_t *slot, const char *name, uint8_t *traps, size_t *used)
{
	for (size_t i = 0; i < sizeof implemented / sizeof implemented[0]; i++) {
		if (!strcmp(implemented[i].name, name)) {
			memcpy(slot, (const void *)&implemented[i].fn, sizeof(pe_fn));
			return 0;
		}
	}
	char *copy = strdup(name);
	if (!copy || *used + TRAP_SIZE > TRAP_AREA) {
		free(copy);
		return -1;
	}
	uint8_t *t = traps + *used;
	write_trap(t, copy);
	*used += TRAP_SIZE;
	memcpy(slot, (const void *)&t, sizeof t);
	return 0;
}

/* --- loading ------------------------------------------------------------------------------------ */

static uint8_t *read_file(const char *path, size_t *len)
{
	FILE *f = fopen(path, "rb");
	if (!f) return NULL;
	uint8_t *data = NULL;
	long size = fseek(f, 0, SEEK_END) == 0 ? ftell(f) : -1;
	if (size > 0 && fseek(f, 0, SEEK_SET) == 0) {
		data = malloc((size_t)size);
		if (data && fread(data, 1, (size_t)size, f) != (size_t)size) {
			free(data);
			data = NULL;
		}
		*len = (size_t)size;
	}
	fclose(f);
	return data;
}

static int in_range(size_t off, size_t n, size_t total) { return off <= total && n <= total - off; }

static int fill_imports(pe_image *img, uint32_t imp, uint8_t *traps);

static int apply_relocations(pe_image *img, uint32_t rel, uint32_t rel_size, int64_t delta)
{
	for (uint32_t off = 0; delta && off < rel_size;) {
		if (!in_range((size_t)rel + off, 8, img->size)) return -1;
		const uint8_t *block = img->base + rel + off;
		uint32_t page = rd32(block), size = rd32(block + 4);
		if (size < 8 || !in_range((size_t)rel + off, size, img->size)) return -1;
		for (uint32_t k = 8; k + 2 <= size; k += 2) {
			uint16_t e = rd16(block + k);
			size_t at = (size_t)page + (e & 0xfff);
			if (e >> 12 != 10) continue; /* only IMAGE_REL_BASED_DIR64 occurs in x64 images */
			if (!in_range(at, 8, img->size)) return -1;
			uint64_t v;
			memcpy(&v, img->base + at, 8);
			v += (uint64_t)delta;
			memcpy(img->base + at, &v, 8);
		}
		off += size;
	}
	return 0;
}

static int link_imports(pe_image *img, uint32_t imp)
{
	/* Written now, made executable (and no longer writable) once every trap is in place. */
	uint8_t *traps = mmap(NULL, TRAP_AREA, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	if (traps == MAP_FAILED) return -1;
	int rc = fill_imports(img, imp, traps);
	if (rc < 0 || mprotect(traps, TRAP_AREA, PROT_READ | PROT_EXEC) != 0) {
		munmap(traps, TRAP_AREA);
		return -1;
	}
	return 0;
}

/* Final page protections from each section's flags, so no page is writable and executable. */
static int protect_sections(pe_image *img, const uint8_t *file, size_t sections, uint16_t nsec, uint32_t header_size)
{
	if (mprotect(img->base, (header_size + 0xfffu) & ~0xfffu, PROT_READ) != 0) return -1;
	for (uint16_t i = 0; i < nsec; i++) {
		const uint8_t *sec = file + sections + 40 * (size_t)i;
		uint32_t vsize = rd32(sec + 8), va = rd32(sec + 12), raw_size = rd32(sec + 16), flags = rd32(sec + 36);
		size_t len = ((size_t)(vsize > raw_size ? vsize : raw_size) + 0xfff) & ~(size_t)0xfff;
		if (!len || !in_range(va, len, img->size)) continue;
		int prot = (flags & 0x40000000u ? PROT_READ : 0)      /* IMAGE_SCN_MEM_READ */
		         | (flags & 0x80000000u ? PROT_WRITE : 0)     /* IMAGE_SCN_MEM_WRITE */
		         | (flags & 0x20000000u ? PROT_EXEC : 0);     /* IMAGE_SCN_MEM_EXECUTE */
		if ((prot & PROT_WRITE) && (prot & PROT_EXEC)) prot &= ~PROT_WRITE;
		if (mprotect(img->base + va, len, prot) != 0) return -1;
	}
	return 0;
}

static int fill_imports(pe_image *img, uint32_t imp, uint8_t *traps)
{
	size_t used = 0;
	for (size_t d = imp; imp && in_range(d, 20, img->size) && rd32(img->base + d + 12); d += 20) {
		const uint8_t *desc = img->base + d;
		uint32_t lookup = rd32(desc) ? rd32(desc) : rd32(desc + 16), iat = rd32(desc + 16);
		for (size_t k = 0;; k++) {
			size_t lk = lookup + 8 * k, slot = iat + 8 * k;
			if (!in_range(lk, 8, img->size) || !in_range(slot, 8, img->size)) return -1;
			uint64_t entry = rd64(img->base + lk);
			if (!entry) break;
			char ordinal[32];
			const char *name = ordinal;
			if (entry >> 63)
				snprintf(ordinal, sizeof ordinal, "%s#%u", (const char *)img->base + rd32(desc + 12),
				         (unsigned)(entry & 0xffff));
			else if (in_range((uint32_t)entry + 2, 1, img->size))
				name = (const char *)img->base + (uint32_t)entry + 2;
			else
				return -1;
			if (resolve(img->base + slot, name, traps, &used) < 0) return -1;
		}
	}
	return 0;
}

pe_image *pe_load(const char *path)
{
	size_t len = 0;
	uint8_t *file = read_file(path, &len);
	if (!file) return NULL;

	pe_image *img = NULL;
	uint32_t pe = len >= 0x40 ? rd32(file + 0x3c) : 0;
	if (len < 0x40 || !in_range(pe, 24 + 112 + 16 * 8, len) || memcmp(file + pe, "PE\0\0", 4) != 0
	    || rd16(file + pe + 4) != 0x8664)
		goto out;
	uint16_t nsec = rd16(file + pe + 6), optsize = rd16(file + pe + 20);
	const uint8_t *opt = file + pe + 24;
	uint64_t image_base = rd64(opt + 24);
	uint32_t image_size = rd32(opt + 56), header_size = rd32(opt + 60);
	const uint8_t *dirs = opt + 112;
	size_t sections = (size_t)pe + 24 + optsize;
	if (header_size > image_size || header_size > len || !in_range(sections, 40 * (size_t)nsec, len)) goto out;

	img = calloc(1, sizeof *img);
	if (!img) goto out;
	img->size = image_size;
	img->export_dir = rd32(dirs + DIR_EXPORT);
	img->export_size = rd32(dirs + DIR_EXPORT + 4);
	uint32_t imp = rd32(dirs + DIR_IMPORT), rel = rd32(dirs + DIR_BASERELOC), rel_size = rd32(dirs + DIR_BASERELOC + 4);
	img->base = mmap(NULL, image_size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	if (img->base == MAP_FAILED) {
		free(img);
		img = NULL;
		goto out;
	}
	memcpy(img->base, file, header_size);
	for (uint16_t i = 0; i < nsec; i++) {
		const uint8_t *s = file + sections + 40 * (size_t)i;
		uint32_t va = rd32(s + 12), raw_size = rd32(s + 16), raw = rd32(s + 20);
		if (raw_size && (!in_range(raw, raw_size, len) || !in_range(va, raw_size, image_size))) goto fail;
		if (raw_size) memcpy(img->base + va, file + raw, raw_size);
	}
	if (apply_relocations(img, rel, rel_size, (int64_t)((uintptr_t)img->base - image_base)) < 0) goto fail;
	if (link_imports(img, imp) < 0) goto fail;
	if (protect_sections(img, file, sections, nsec, header_size) < 0) goto fail;
	if (getenv("PELOADER_DEBUG")) fprintf(stderr, "peloader: %s at %p\n", path, (void *)img->base);
	goto out;

fail:
	munmap(img->base, image_size);
	free(img);
	img = NULL;
out:
	free(file);
	return img;
}

pe_fn pe_function(pe_image *img, const char *name)
{
	pe_fn fn = NULL;
	if (!in_range(img->export_dir, 40, img->size)) return NULL;
	const uint8_t *e = img->base + img->export_dir;
	uint32_t count = rd32(e + 24), funcs = rd32(e + 28), names = rd32(e + 32), ords = rd32(e + 36);
	for (uint32_t i = 0; i < count; i++) {
		size_t name_at = names + 4 * (size_t)i, ord_at = ords + 2 * (size_t)i;
		if (!in_range(name_at, 4, img->size) || !in_range(ord_at, 2, img->size)) break;
		uint32_t name_rva = rd32(img->base + name_at);
		if (!in_range(name_rva, 1, img->size) || strcmp((const char *)img->base + name_rva, name) != 0) continue;
		size_t slot = funcs + 4 * (size_t)rd16(img->base + ord_at);
		if (!in_range(slot, 4, img->size)) break;
		uint8_t *addr = img->base + rd32(img->base + slot);
		memcpy((void *)&fn, (const void *)&addr, sizeof fn); /* code address -> function pointer, as with dlsym */
		break;
	}
	return fn;
}

void *pe_rva(pe_image *img, unsigned rva)
{
	return rva < img->size ? img->base + rva : NULL;
}

int pe_patch(pe_image *img, unsigned rva, const void *expect, const void *bytes, size_t n)
{
	if (!in_range(rva, n, img->size) || memcmp(img->base + rva, expect, n) != 0) return -1;
	uintptr_t start = (uintptr_t)(img->base + rva) & ~(uintptr_t)0xfff;
	size_t len = ((uintptr_t)(img->base + rva) + n - start + 0xfff) & ~(size_t)0xfff;
	if (mprotect((void *)start, len, PROT_READ | PROT_WRITE) != 0) return -1;
	memcpy(img->base + rva, bytes, n);
	return mprotect((void *)start, len, PROT_READ | PROT_EXEC);   /* only code is patched */
}
