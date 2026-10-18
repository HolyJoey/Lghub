/*
 * DTS Headphone:X 2.0, the surround effect G HUB offers for its headsets, called straight from
 * Logitech's playback APO (logi_audio_hx2e_render_apo.dll). No Wine.
 *
 * The DLL doesn't export the DSP, but its C++ object does all the work and has a plain vtable
 * (DTSheadphoneX2E, made by a factory function). We call it the way the APO's
 * LogiGamingAudioHX2EDspModule does:
 *   obj = factory()
 *   obj->Init(&device_name)               the tuning: "PRO_X", "G733", ...
 *   obj->SetStreamsParams(rate, channels, room or stereo id, state)
 *   obj->SetParam(which, value)           later changes: 0 state, 1 room, 2 stereo
 *   obj->Process(out, in, frames)         interleaved float, out is stereo
 * Function offsets are for this exact DLL build (fetch.py checks its SHA-256), and the code at
 * them is checked too, so another build fails cleanly.
 */
#include "hx2e.h"
#include "peloader.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define WINAPI __attribute__((ms_abi))

#define RVA_FACTORY     0x55e40   /* new DTSheadphoneX2E */
#define RVA_LOG_CMP     0x65749   /* logger: cmp ecx, [log level] */
#define RVA_LOG_LEVEL   0x1dd260
#define RVA_CHKSTK      0x67020   /* __chkstk */

/* vtable slots of DTSheadphoneX2E */
enum { V_DELETE = 0, V_INIT = 2, V_SET = 3, V_STREAMS = 5, V_PROCESS = 6 };

typedef WINAPI void *(*factory_fn)(void);
typedef WINAPI void *(*delete_fn)(void *, unsigned);
typedef WINAPI char (*init_fn)(void *, void *);
typedef WINAPI char (*set_fn)(void *, int, int);
typedef WINAPI char (*streams_fn)(void *, int, int, int, unsigned char);
typedef WINAPI char (*process_fn)(void *, float *, float *, unsigned);

/* MSVC's std::wstring: up to 7 wide chars inline, else a pointer to them; then size and capacity. */
struct msvc_wstring {
	union {
		uint16_t buf[8];
		uint16_t *ptr;
	} data;
	uint64_t size, capacity;
};

struct hx2e {
	void *obj;
	void **vtable;
	int channels, room, stereo;
};

static pe_image *dll;

static void *slot(const hx2e *h, int i) { return h->vtable[i]; }

/*
 * The DLL logs through a function that takes a mutex and writes files once a message's level is
 * at or below a global; setting the global to 0 turns it into a no-op (nothing we'd see anyway).
 */
static int quiet_logger(pe_image *img)
{
	static const unsigned char expect[] = {0x3b, 0x0d, 0x11, 0x7b, 0x17, 0x00}; /* cmp ecx, [level] */
	const unsigned char *code = pe_rva(img, RVA_LOG_CMP);
	int32_t *level = pe_rva(img, RVA_LOG_LEVEL);
	if (!code || !level || memcmp(code, expect, sizeof expect) != 0) return -1;
	*level = 0;
	return 0;
}

/*
 * __chkstk touches each new stack page of a big frame, finding the stack's end in the Windows
 * thread block (gs:0x10), which a Linux thread doesn't have. Linux grows the stack by itself, so
 * the probe can simply return.
 */
static int no_stack_probe(pe_image *img)
{
	static const unsigned char expect[] = {0x48, 0x83, 0xec, 0x10}; /* sub rsp, 0x10 */
	static const unsigned char ret[] = {0xc3, 0x90, 0x90, 0x90};
	return pe_patch(img, RVA_CHKSTK, expect, ret, sizeof ret);
}

/* Init takes the string by value and frees a heap buffer with the CRT's free(), which the
 * loader maps to ours, so a long name can live in malloc'ed memory. */
static int set_name(struct msvc_wstring *s, const char *name)
{
	size_t n = strlen(name);
	uint16_t *chars = s->data.buf;
	memset(s, 0, sizeof *s);
	if (n > 7) {
		chars = calloc(n + 1, sizeof *chars);
		if (!chars) return -1;
		s->data.ptr = chars;
	}
	for (size_t i = 0; i < n; i++) chars[i] = (uint16_t)name[i];
	s->size = n;
	s->capacity = n > 7 ? n : 7;
	return 0;
}

hx2e *hx2e_open(const char *dll_path, const char *headset, int rate, int channels)
{
	if (rate != 44100 && rate != 48000) return NULL;   /* the tunings exist for these two */
	if (channels != 2 && channels != 6 && channels != 8) return NULL;
	if (!dll) {
		dll = pe_load(dll_path);
		if (!dll) return NULL;
		if (quiet_logger(dll) || no_stack_probe(dll)) {
			fprintf(stderr, "hx2e: unexpected DLL build; expected Logitech's 2024.7 HX2E APO\n");
			return NULL;
		}
	}
	factory_fn factory;
	void *at = pe_rva(dll, RVA_FACTORY);
	memcpy((void *)&factory, (const void *)&at, sizeof factory);
	hx2e *h = calloc(1, sizeof *h);
	if (!h) return NULL;
	h->obj = factory();
	if (!h->obj) { free(h); return NULL; }
	memcpy((void *)&h->vtable, h->obj, sizeof h->vtable);
	h->channels = channels;
	h->room = 0;
	h->stereo = 0;

	struct msvc_wstring name;
	if (set_name(&name, headset)) { hx2e_close(h); return NULL; }
	init_fn init = (init_fn)slot(h, V_INIT);
	streams_fn streams = (streams_fn)slot(h, V_STREAMS);
	if (!init(h->obj, &name)) {
		fprintf(stderr, "hx2e: Init(%s) failed\n", headset);
		hx2e_close(h);
		return NULL;
	}
	if (!streams(h->obj, rate, channels, channels == 2 ? h->stereo : h->room, 1)) {
		fprintf(stderr, "hx2e: SetStreamsParams(%d Hz, %d channels) failed\n", rate, channels);
		hx2e_close(h);
		return NULL;
	}
	return h;
}

int hx2e_set(hx2e *h, int which, int value)
{
	set_fn set = (set_fn)slot(h, V_SET);
	if (!set(h->obj, which, value)) return -1;
	if (which == HX2E_ROOM) h->room = value;
	if (which == HX2E_STEREO) h->stereo = value;
	return 0;
}

int hx2e_process(hx2e *h, const float *in, float *out, unsigned frames)
{
	process_fn process = (process_fn)slot(h, V_PROCESS);
	return process(h->obj, out, (float *)in, frames) ? 0 : -1;
}

int hx2e_channels(const hx2e *h) { return h->channels; }

void hx2e_close(hx2e *h)
{
	if (!h) return;
	/* The destructor's release path already frees the object (traced: one free per object with
	 * flag 0), so it is called without its own "delete this" flag. */
	if (h->obj) ((delete_fn)slot(h, V_DELETE))(h->obj, 0);
	free(h);
}
