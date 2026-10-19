/*
 * Blue VO!CE 2 (DTS ClearVoice 2), the voice chain G HUB uses for the Yeti mics, G735 and PRO X 2,
 * called straight from Logitech's capture APO (logi_audio_dts_clearvoice_2_capture_apo.dll).
 * No Wine.
 *
 * Mirrors CDTSClearVoice2APOGFX::InitDTS / ProcessDTS / GetUserSettings in the DLL:
 *   config = {rate, block, channels, rate, block, 2, default parameters, 1}
 *   dtsClearVoice2GetInstanceSize(&config, &size), 32-byte aligned instance, dtsClearVoice2Init
 *   parameters: GetParameters, then each property-store value written to its field, then
 *   UpdateParameters (the APO's setter lambdas; the pid -> field table below is decoded from them)
 *   dtsClearVoice2Process(inst, channels[]) in place, one 256-frame block at a time (44.1/48 kHz)
 */
#include "bv2.h"
#include "peloader.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define WINAPI __attribute__((ms_abi))
#define PARAMS_SIZE 0x1a0
#define CONFIG_SIZE 0x1c0
#define CONFIG_PARAMS 0x18
#define CONFIG_FLAG 0x1b8

typedef WINAPI int (*params_fn)(void *);
typedef WINAPI int (*size_fn)(const void *, uint64_t *);
typedef WINAPI int (*init_fn)(void *, const void *);
typedef WINAPI int (*inst_params_fn)(void *, void *);
typedef WINAPI int (*process_fn)(void *, float **);
typedef WINAPI int (*release_fn)(void *);

#define API(name, args) "?dtsClearVoice2" name "@DtsClearVoice2_API_V1@@YA?AW4DtsClearVoice2Result@1@" args

/* pid -> (byte offset in DtsClearVoice2Parameters, is a switch), from the APO's setter lambdas
 * (one per property key, in the order of its key table). Pids 3 and 4 aren't parameters. */
static const struct { unsigned short pid, offset; unsigned char flag; } fields[] = {
	{100, 12, 0}, {101, 16, 0}, {102, 24, 0}, {103, 20, 1},
	{200, 28, 0}, {201, 32, 0}, {202, 36, 0}, {203, 40, 0}, {204, 48, 0}, {205, 44, 1},
	{300, 52, 0}, {301, 56, 0}, {302, 60, 0}, {303, 64, 0}, {304, 68, 0}, {305, 72, 0}, {306, 76, 0},
	{307, 80, 0}, {308, 84, 0}, {309, 88, 0}, {310, 92, 0}, {311, 100, 0}, {312, 96, 1}, {313, 97, 1},
	{314, 98, 1},
	{400, 148, 0}, {401, 152, 0}, {402, 104, 0}, {403, 108, 0}, {404, 112, 0}, {405, 120, 0},
	{406, 116, 0}, {407, 124, 0}, {408, 132, 0}, {409, 128, 0}, {410, 136, 0}, {411, 144, 0},
	{412, 140, 0}, {413, 160, 0}, {414, 156, 1},
	{500, 164, 0}, {501, 168, 0}, {502, 172, 0}, {503, 176, 0}, {504, 180, 0}, {505, 196, 0},
	{506, 204, 0}, {507, 221, 1}, {508, 184, 0}, {509, 188, 0}, {510, 192, 0}, {511, 208, 0},
	{512, 212, 0}, {513, 222, 1}, {514, 200, 0}, {515, 216, 0}, {516, 220, 1},
	{600, 224, 0}, {601, 228, 0}, {602, 240, 0}, {603, 232, 0}, {604, 236, 0}, {605, 244, 0},
	{606, 248, 1}, {607, 252, 0}, {608, 256, 0}, {609, 260, 0}, {610, 264, 0}, {611, 268, 0},
	{612, 276, 0}, {613, 272, 1},
	{700, 280, 0}, {701, 284, 0}, {702, 288, 0}, {703, 292, 0}, {704, 296, 1},
	{800, 300, 0}, {801, 304, 0}, {802, 308, 0}, {803, 312, 0}, {804, 316, 1},
	{900, 320, 0}, {901, 324, 0}, {902, 328, 0}, {903, 332, 0}, {904, 336, 1},
	{1000, 340, 0}, {1001, 344, 0}, {1002, 348, 0}, {1003, 352, 0}, {1004, 356, 0}, {1005, 360, 0},
	{1006, 364, 0}, {1007, 368, 0}, {1008, 372, 0}, {1009, 376, 1},
	{1100, 380, 0}, {1101, 384, 0}, {1102, 388, 0}, {1103, 392, 0}, {1104, 396, 0}, {1105, 400, 0},
	{1106, 404, 0}, {1107, 408, 0}, {1108, 412, 1},
};

/* G HUB's setting names (BlueVoice2.Settings in its microphone.proto, as its presets spell them) ->
 * pid, from the agent's APO <-> settings code (one lambda per pid, field offsets matched against the
 * generated protobuf offset table). volume (pid 3) and the on/off switch (pid 1) aren't DSP
 * parameters; inputGain is the mic's own gain. */
static const struct { const char *name; unsigned short pid; } names[] = {
	{"highPassFilter.enabled", 103}, {"highPassFilter.frequency", 101},
	{"noiseReduction.enabled", 205}, {"noiseReduction.sensitivity", 201}, {"noiseReduction.bias", 202},
	{"noiseReduction.maxAttenuation", 203}, {"noiseReduction.release", 200},
	{"gatingCompressor.noiseGateEnabled", 312}, {"gatingCompressor.noiseGateThreshold", 300},
	{"gatingCompressor.noiseGateMaxAttenuation", 301}, {"gatingCompressor.noiseGateAttack", 302},
	{"gatingCompressor.noiseGateRelease", 303}, {"gatingCompressor.noiseGateHoldTime", 304},
	{"gatingCompressor.compressorEnabled", 313}, {"gatingCompressor.compressorThreshold", 305},
	{"gatingCompressor.compressorRatio", 306}, {"gatingCompressor.compressorPreGain", 307},
	{"gatingCompressor.compressorPostGain", 308}, {"gatingCompressor.compressorAttack", 309},
	{"gatingCompressor.compressorRelease", 310},
	{"multiBandEq.enabled", 414},
	{"multiBandEq.lowBandFilter.frequency", 404}, {"multiBandEq.lowBandFilter.gain", 406},
	{"multiBandEq.lowBandFilter.q", 405}, {"multiBandEq.midBandFilter.frequency", 407},
	{"multiBandEq.midBandFilter.gain", 409}, {"multiBandEq.midBandFilter.q", 408},
	{"multiBandEq.highBandFilter.frequency", 410}, {"multiBandEq.highBandFilter.gain", 412},
	{"multiBandEq.highBandFilter.q", 411},
	{"dePopper.enabled", 507}, {"dePopper.threshold", 500}, {"dePopper.frequency", 502},
	{"dePopper.width", 503}, {"dePopper.maxAttenuation", 504}, {"dePopper.attack", 505},
	{"dePopper.release", 506},
	{"deEsser.enabled", 513}, {"deEsser.threshold", 501}, {"deEsser.frequency", 508},
	{"deEsser.width", 509}, {"deEsser.maxAttenuation", 510}, {"deEsser.attack", 511},
	{"deEsser.release", 512},
	{"hardLimiter.enabled", 904}, {"hardLimiter.attack", 900}, {"hardLimiter.release", 901},
	{"hardLimiter.boost", 902},
};

struct bv2 {
	inst_params_fn get, update;
	process_fn process;
	release_fn release;
	void *inst;
	unsigned char params[PARAMS_SIZE];
	float *buf[2];                 /* like the APO: two channel buffers, even for mono */
	int block;
	int bypass;                    /* "enabled 0": audio passes through untouched (ours) */
};

static pe_image *dll;

static pe_fn api(const char *name)
{
	return dll ? pe_function(dll, name) : NULL;
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

static void *alloc32(size_t n)
{
	void *p = aligned_alloc(32, (n + 31) & ~(size_t)31);
	if (p) memset(p, 0, n);
	return p;
}

bv2 *bv2_open(const char *dll_path, int rate)
{
	int block = block_for_rate(rate);
	if (!block) return NULL;
	if (!dll && !(dll = pe_load(dll_path))) return NULL;
	params_fn defaults = (params_fn)api(API("GetDefaultParameters", "PEAUDtsClearVoice2Parameters@1@@Z"));
	size_fn size = (size_fn)api(API("GetInstanceSize", "PEBUDtsClearVoice2Config@1@PEA_K@Z"));
	init_fn init = (init_fn)api(API("Init", "PEAUDtsClearVoice2Inst@1@PEBUDtsClearVoice2Config@1@@Z"));
	bv2 *b = calloc(1, sizeof *b);
	if (!b) return NULL;
	b->get = (inst_params_fn)api(API("GetParameters", "PEAUDtsClearVoice2Inst@1@PEAUDtsClearVoice2Parameters@1@@Z"));
	b->update = (inst_params_fn)api(API("UpdateParameters", "PEAUDtsClearVoice2Inst@1@PEAUDtsClearVoice2Parameters@1@@Z"));
	b->process = (process_fn)api(API("Process", "PEAUDtsClearVoice2Inst@1@PEAPEAM@Z"));
	b->release = (release_fn)api(API("Release", "PEAUDtsClearVoice2Inst@1@@Z"));
	if (!defaults || !size || !init || !b->get || !b->update || !b->process || !b->release) {
		fprintf(stderr, "bv2: the DLL doesn't have the ClearVoice 2 API\n");
		free(b);
		return NULL;
	}
	unsigned char config[CONFIG_SIZE] = {0};
	int32_t head[6] = {rate, block, 1, rate, block, 2};
	memcpy(config, head, sizeof head);
	uint64_t inst_size = 0;
	if (defaults(config + CONFIG_PARAMS) || (config[CONFIG_FLAG] = 1, size(config, &inst_size)) || !inst_size) {
		free(b);
		return NULL;
	}
	b->block = block;
	b->inst = alloc32((size_t)inst_size);
	b->buf[0] = alloc32((size_t)block * sizeof(float));
	b->buf[1] = alloc32((size_t)block * sizeof(float));
	if (!b->inst || !b->buf[0] || !b->buf[1] || init(b->inst, config) || b->get(b->inst, b->params)) {
		bv2_close(b);
		return NULL;
	}
	return b;
}

int bv2_block(const bv2 *b) { return b->block; }

int bv2_set(bv2 *b, unsigned pid, float value)
{
	for (size_t i = 0; i < sizeof fields / sizeof fields[0]; i++) {
		if (fields[i].pid != pid) continue;
		if (fields[i].flag) b->params[fields[i].offset] = value != 0.0f;
		else memcpy(b->params + fields[i].offset, &value, sizeof value);
		return 0;
	}
	return -1;
}

int bv2_set_name(bv2 *b, const char *name, float value)
{
	if (!strcmp(name, "enabled")) {   /* G HUB's on/off (pid 1), not a DSP parameter */
		b->bypass = value == 0.0f;
		return 0;
	}
	for (size_t i = 0; i < sizeof names / sizeof names[0]; i++)
		if (!strcmp(names[i].name, name)) return bv2_set(b, names[i].pid, value);
	return -1;
}

int bv2_supports_rate(int rate) { return block_for_rate(rate) != 0; }

int bv2_load_params(bv2 *b, const char *path)
{
	FILE *f = fopen(path, "r");
	if (!f) return -1;
	char line[256];
	while (fgets(line, sizeof line, f)) {
		/* "name value" with G HUB's names; anything else (comments, blank lines, bad numbers) is skipped */
		char *name = strtok(line, " \t\r\n"), *text = strtok(NULL, " \t\r\n"), *end;
		if (!name || !text || name[0] == '#') continue;
		float value = strtof(text, &end);
		if (end != text && !*end) bv2_set_name(b, name, value);
	}
	int rc = fclose(f) == 0 ? 0 : -1;
	return bv2_apply(b) ? -1 : rc;
}

int bv2_apply(bv2 *b)
{
	return b->update(b->inst, b->params) ? -1 : 0;
}

int bv2_process(bv2 *b, const float *in, float *out)
{
	if (b->bypass) {
		memmove(out, in, (size_t)b->block * sizeof(float));
		return 0;
	}
	memcpy(b->buf[0], in, (size_t)b->block * sizeof(float));
	if (b->process(b->inst, b->buf)) return -1;
	memcpy(out, b->buf[0], (size_t)b->block * sizeof(float));
	return 0;
}

void bv2_close(bv2 *b)
{
	if (!b) return;
	if (b->inst && b->release) b->release(b->inst);
	free(b->inst);
	free(b->buf[0]);
	free(b->buf[1]);
	free(b);
}
