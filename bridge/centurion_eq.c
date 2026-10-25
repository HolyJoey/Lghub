/*
 * centurion-eq — the newer headsets' onboard equalizer coefficients (feature 0x0636), made by
 * Logitech's own code: loads G HUB's lghub_agent.exe (peloader.c, no Wine) and runs the filter
 * designer it uses for these headsets, then packs the result as G HUB does (FUN_142231a50).
 *
 *   centurion-eq --exe lghub_agent.exe MASK FREQ:GAIN:Q ...  -> the coefficient block (hex)
 *
 * MASK is byte 1 of the headset's EQ info (sample rates, bit n = RATES[n]); each band is its
 * frequency (Hz), gain (dB, signed) and q byte as the headset reports them. RVAs are those of
 * the agent build G HUB 2026.6 ships (Python checks its SHA-256 before running this).
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "peloader.h"

#define WINAPI __attribute__((ms_abi))
#define RVA_INIT 0x236f1e0      /* (id, rate, bands, 1, 0, 0) */
#define RVA_BAND 0x236f280      /* (id, band, freq, gain, q) */
#define RVA_DESIGN 0x236d910    /* (id) */
#define RVA_FINISH 0x236d620    /* (id, 0.0) */
#define RVA_COUNT 0x236f130     /* (id) -> number of 16-bit coefficients */
#define RVA_COEFFS 0x236f1c0    /* (id) -> the coefficients */
#define RVA_RELEASE 0x236d8f0   /* (id) */
#define MAX_BANDS 16
#define MAX_OUT 4096

typedef WINAPI void (*init_fn)(int id, double rate, int bands, int one, int zero1, int zero2);
typedef WINAPI void (*band_fn)(int id, int band, double freq, double gain, double q);
typedef WINAPI void (*id_fn)(int id);
typedef WINAPI void (*finish_fn)(int id, double zero);
typedef WINAPI uint16_t (*count_fn)(int id);
typedef WINAPI const uint8_t *(*coeffs_fn)(int id);

/* G HUB's sample rates by mask bit (0x144010dd0..0x144010e00) */
static const double RATES[8] = {0, 96000, 88200, 48000, 44100, 24000, 16000, 8000};

struct out { uint8_t b[MAX_OUT]; size_t n; };

static int put(struct out *o, unsigned v)
{
	if (o->n >= MAX_OUT) return -1;
	o->b[o->n++] = (uint8_t)v;
	return 0;
}

/* "FREQ:GAIN:Q" -> three checked numbers; -1 if it isn't that */
static int parse_band(const char *s, long out[3])
{
	for (int i = 0; i < 3; i++) {
		char *end = NULL;
		out[i] = strtol(s, &end, 10);
		if (end == s || *end != (i < 2 ? ':' : '\0')) return -1;
		s = end + 1;
	}
	return 0;
}

int main(int argc, char **argv)
{
	if (argc < 5 || strcmp(argv[1], "--exe") != 0 || argc - 4 > MAX_BANDS) {
		(void)fprintf(stderr, "usage: %s --exe lghub_agent.exe MASK FREQ:GAIN:Q ...\n", argv[0]);
		return 2;
	}
	char *end = NULL;
	unsigned long mask = strtoul(argv[3], &end, 0);
	if (end == argv[3] || *end || mask > 0xffu) {
		(void)fprintf(stderr, "centurion-eq: bad rate mask %s\n", argv[3]);
		return 2;
	}
	int bands = argc - 4;
	double freq[MAX_BANDS], gain[MAX_BANDS], q[MAX_BANDS];
	for (int i = 0; i < bands; i++) {
		long v[3];
		if (parse_band(argv[4 + i], v) || v[0] <= 0 || v[0] > 0xffff || v[1] < -128 || v[1] > 127
		    || v[2] <= 0 || v[2] > 255) {                    /* q 0: G HUB stops there */
			(void)fprintf(stderr, "centurion-eq: bad band %s\n", argv[4 + i]);
			return 2;
		}
		freq[i] = (double)v[0];
		gain[i] = (double)v[1];
		q[i] = (double)v[2];
	}
	pe_image *img = pe_load(argv[2]);
	if (!img) {
		(void)fprintf(stderr, "centurion-eq: cannot load %s\n", argv[2]);
		return 1;
	}
	struct out o = {{0}, 0};
	unsigned rates = 0;
	for (int bit = 0; bit < 8; bit++) rates += (unsigned)(mask >> (unsigned)bit) & 1u;
	const uint8_t head[7] = {3, 0x0e, 0, (uint8_t)rates, 0, 0, 0};
	for (int i = 0; i < 7; i++) (void)put(&o, head[i]);
	for (int bit = 4; bit > 2; bit--) {                  /* 44.1 then 48 kHz, as G HUB's loop */
		if (!((mask >> (unsigned)bit) & 1u)) continue;
		((init_fn)pe_rva(img, RVA_INIT))(0, RATES[bit], bands, 1, 0, 0);
		for (int i = 0; i < bands; i++) ((band_fn)pe_rva(img, RVA_BAND))(0, i, freq[i], gain[i], q[i]);
		((id_fn)pe_rva(img, RVA_DESIGN))(0);
		((finish_fn)pe_rva(img, RVA_FINISH))(0, 0.0);
		unsigned count = ((count_fn)pe_rva(img, RVA_COUNT))(0);
		const uint8_t *c = ((coeffs_fn)pe_rva(img, RVA_COEFFS))(0);
		if (put(&o, bit == 3 ? 2 : 1) || put(&o, 0) || put(&o, count & 0xffu) || put(&o, count >> 8u)) return 1;
		for (unsigned k = 0; k < count * 2; k++)
			if (put(&o, c[k])) return 1;
		((id_fn)pe_rva(img, RVA_RELEASE))(0);
	}
	/* G HUB puts [5, 'Z', length lo, length hi] in front (the length of what follows) */
	(void)printf("055a%02x%02x", (unsigned)(o.n & 0xffu), (unsigned)(o.n >> 8u) & 0xffu);
	for (size_t i = 0; i < o.n; i++) (void)printf("%02x", o.b[i]);
	(void)printf("\n");
	return 0;
}
