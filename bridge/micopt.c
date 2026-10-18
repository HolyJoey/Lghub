/*
 * DTS MicOpt, the DSP behind Blue VO!CE 1, called straight from Logitech's APO DLL.
 *
 * Mirrors what the APO does (CDTSStudioAPOGFX::InitDTS / ProcessDTS in the DLL):
 *   dts_micopt_get_sizes(&state, &params, &temp, channels, block)
 *   dts_micopt_init(state, params, channels, block, rate)
 *   defaults via dts_micopt_set, then the user's parameters
 *   dts_micopt_process(state, params, temp, in[channels], out[channels]) per block
 * Block size is 256 frames at 44.1/48 kHz, 512 at 88.2/96 kHz, 1024 at 176.4/192 kHz.
 */
#include "micopt.h"
#include "peloader.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define WINAPI __attribute__((ms_abi))

typedef WINAPI int (*get_sizes_fn)(int *, int *, int *, unsigned long long, int);
typedef WINAPI int (*init_fn)(void *, void *, int, int, int);
typedef WINAPI int (*set_fn)(void *, void *, const char *, float *);
typedef WINAPI int (*process_fn)(void *, void *, void *, float **, float **);

struct micopt {
	set_fn set;
	process_fn process;
	void *state, *params, *temp;
	/* The DSP may write to its input, so it gets private copies. Like the APO, it always gets two
	 * input and two output buffers, even for mono (the second pair is scratch). */
	float *in[2], *out[2];
	int block, rate;
};

/* The APO's own defaults, in its order (FUN_18000e080). */
static const struct { const char *name; float value; } defaults[] = {
	{"micopt.enable", 1}, {"micopt.balance", 0}, {"micopt.volume", 1},
	{"dpop.enable", 0}, {"dpop.freq", 80},
	{"nr.enable", 0}, {"nr.release", 75}, {"nr.sensitivity", 25}, {"nr.bias", 2.5f}, {"nr.attenuation_max", -20},
	{"exp.enable", 0}, {"exp.attack", 5}, {"exp.release", 250}, {"exp.hysteresis", 5}, {"exp.ratio", 2},
	{"exp.thresh", -48}, {"exp.thresh_auto_enable", 0}, {"exp.thresh_auto_sense", 20}, {"exp.attenuation_max", -20},
	{"veq.enable", 0}, {"veq.low_gain", 1}, {"veq.low_freq", 250}, {"veq.low_width", 1}, {"veq.mid_gain", 1},
	{"veq.mid_freq", 3000}, {"veq.mid_width", 4}, {"veq.high_gain", 1}, {"veq.high_freq", 8000}, {"veq.high_width", 1},
	{"des.enable", 0}, {"des.attack", 5}, {"des.release", 250}, {"des.ratio", 4}, {"des.thresh", 0}, {"des.freq", 8000},
	{"comp.enable", 0}, {"comp.attack", 5}, {"comp.release", 250}, {"comp.ratio", 4}, {"comp.thresh", -20}, {"comp.makeup", 1},
	{"lim.boost", 1}, {"lim.attack", 5}, {"lim.release", 250},
};

static pe_image *dll;

static int set_raw(micopt *m, const char *name, void *value);

/*
 * The one piece of the DLL's C-runtime start-up the DSP needs. On a math edge case (log10(0) on
 * silence, say) the CRT calls a user "matherr" handler through a pointer it keeps encoded with
 * the security cookie: ror(cookie ^ stored, cookie & 63), where 0 means "none". Start-up would
 * store encode(NULL) = cookie; without it the decode yields garbage and the call crashes.
 * Offsets are for this exact DLL build (fetch.py checks its SHA-256); the code bytes are checked
 * too, so a different build fails cleanly instead of being patched blindly.
 */
#define RVA_SECURITY_COOKIE 0x57330
#define RVA_USER_MATHERR    0x59958
#define RVA_INVOKE_MATHERR  0x2df40
#define RVA_USE_FMA3_LIB    0x594e8

static int init_crt_matherr(pe_image *img)
{
	static const unsigned char expect[] = {0x48, 0x8b, 0x15, 0xe9, 0x93, 0x02, 0x00, /* mov rdx, [cookie] */
	                                       0x4c, 0x8b, 0xc1, 0x8b, 0xca,
	                                       0x48, 0x33, 0x15, 0x05, 0xba, 0x02, 0x00}; /* xor rdx, [matherr] */
	const unsigned char *code = pe_rva(img, RVA_INVOKE_MATHERR);
	if (!code || memcmp(code, expect, sizeof expect)) return -1;
	*(unsigned long long *)pe_rva(img, RVA_USER_MATHERR) = *(unsigned long long *)pe_rva(img, RVA_SECURITY_COOKIE);
	if (getenv("MICOPT_FMA3")) *(int *)pe_rva(img, RVA_USE_FMA3_LIB) = atoi(getenv("MICOPT_FMA3"));
	return 0;
}

static int block_for_rate(int rate)
{
	switch (rate) {
	case 44100: case 48000: return 256;
	case 88200: case 96000: return 512;
	case 176400: case 192000: return 1024;
	default: return 0;
	}
}

micopt *micopt_open(const char *dll_path, int rate)
{
	int block = block_for_rate(rate);
	if (!block) return NULL;
	if (!dll) {
		if (!(dll = pe_load(dll_path))) return NULL;
		if (init_crt_matherr(dll)) {
			fprintf(stderr, "micopt: unexpected DLL build; expected Logitech's 2024.7 Blue VO!CE APO\n");
			return NULL;
		}
	}
	get_sizes_fn get_sizes = (get_sizes_fn)pe_symbol(dll, "dts_micopt_get_sizes");
	init_fn init = (init_fn)pe_symbol(dll, "dts_micopt_init");
	micopt *m = calloc(1, sizeof *m);
	m->set = (set_fn)pe_symbol(dll, "dts_micopt_set");
	m->process = (process_fn)pe_symbol(dll, "dts_micopt_process");
	if (!get_sizes || !init || !m->set || !m->process) { free(m); return NULL; }

	int state_size, params_size, temp_size;
	if (get_sizes(&state_size, &params_size, &temp_size, 1, block)) { free(m); return NULL; }
	m->block = block;
	m->rate = rate;
	m->state = aligned_alloc(64, (state_size + 63) & ~63);
	m->params = aligned_alloc(64, (params_size + 63) & ~63);
	m->temp = aligned_alloc(64, (temp_size + 63) & ~63);
	for (int c = 0; c < 2; c++) {
		m->in[c] = aligned_alloc(64, block * sizeof(float));
		m->out[c] = aligned_alloc(64, block * sizeof(float));
		memset(m->in[c], 0, block * sizeof(float));
	}
	if (init(m->state, m->params, 1, block, rate)) { micopt_close(m); return NULL; }
	for (size_t i = 0; i < sizeof defaults / sizeof defaults[0]; i++) {
		float v = defaults[i].value; /* FUN_18000e080 passes every default as a float */
		set_raw(m, defaults[i].name, &v);
	}
	return m;
}

int micopt_block(const micopt *m) { return m->block; }

int micopt_rate(const micopt *m) { return m->rate; }

int micopt_supports_rate(int rate) { return block_for_rate(rate) != 0; }

/* Parameters G HUB stores as integers (VT_I4). The APO's GetUserSettings hands the DSP their raw
 * integer bits through the float pointer, and the DSP reads them back as integers, so passing 1.0f
 * would be wrong. Everything else is VT_R4 and passed as a float. */
static int is_integer_param(const char *name)
{
	size_t n = strlen(name);
	return n >= 7 && !strcmp(name + n - 7, ".enable");
}

static int set_raw(micopt *m, const char *name, void *value)
{
	char buf[64] = {0}; /* the DLL compares up to 64 bytes */
	snprintf(buf, sizeof buf, "%s", name);
	return m->set(m->state, m->params, buf, value);
}

int micopt_set(micopt *m, const char *name, float value)
{
	if (is_integer_param(name)) {
		int i = (int)value;
		return set_raw(m, name, &i);
	}
	return set_raw(m, name, &value);
}

int micopt_load_params(micopt *m, const char *path)
{
	FILE *f = fopen(path, "r");
	if (!f) return -1;
	char line[256], name[128];
	float value;
	while (fgets(line, sizeof line, f)) {
		if (line[0] == '#' || sscanf(line, "%127s %f", name, &value) != 2) continue;
		/* GetUserSettings skips balance for a mono stream, and meters are not used here */
		if (!strcmp(name, "micopt.meter_enable") || !strcmp(name, "micopt.balance")) continue;
		micopt_set(m, name, value);
	}
	fclose(f);
	return 0;
}

int micopt_process(micopt *m, const float *in, float *out)
{
	memcpy(m->in[0], in, m->block * sizeof(float));
	int rc = m->process(m->state, m->params, m->temp, m->in, m->out);
	memcpy(out, m->out[0], m->block * sizeof(float));
	return rc;
}

void micopt_close(micopt *m)
{
	if (!m) return;
	free(m->state); free(m->params); free(m->temp);
	for (int c = 0; c < 2; c++) { free(m->in[c]); free(m->out[c]); }
	free(m);
}
