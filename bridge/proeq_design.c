/*
 * proeq-design — the G Pro X PRO equalizer's band maths, done by Logitech's own code: loads
 * logi_audio_conexant.dll (peloader.c, no Wine) and calls its CX2089x band design and analysis.
 *
 *   design TYPE FREQ Q GAIN256   -> the 11-byte coefficient record the chip takes (hex), status
 *   analyse HEX22                -> TYPE FREQ Q GAIN256 of a record the chip holds
 *
 * TYPE / FREQ / Q / GAIN256 are G HUB's band parameters (u16 type in the low 4 bits, u16 Hz,
 * u16 Q, s16 gain in dB x 256). RVAs are those of the DLL build G HUB 2026.6 ships:
 * FUN_180001000 design (rate, params, record) and FUN_1800011e0 analysis (rate, record, params).
 *
 * Usage: proeq-design --dll logi_audio_conexant.dll design|analyse ...
 */
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "peloader.h"

#define WINAPI __attribute__((ms_abi))
#define RVA_DESIGN 0x1000
#define RVA_ANALYSE 0x11e0
#define RATE 48000

typedef WINAPI uint32_t (*design_fn)(uint32_t rate, const uint16_t *params, uint8_t *record);
typedef WINAPI int (*analyse_fn)(uint32_t rate, const uint8_t *record, uint16_t *params);

static int hex_byte(const char *s, uint8_t *out)
{
	char pair[3] = {s[0], s[1], 0};
	char *end = NULL;
	unsigned long v = strtoul(pair, &end, 16);
	if (end != pair + 2) return -1;
	*out = (uint8_t)v;
	return 0;
}

int main(int argc, char **argv)
{
	if (argc < 4 || strcmp(argv[1], "--dll") != 0) {
		(void)fprintf(stderr, "usage: %s --dll DLL design TYPE FREQ Q GAIN256 | analyse HEX22\n", argv[0]);
		return 2;
	}
	pe_image *img = pe_load(argv[2]);
	if (!img) {
		(void)fprintf(stderr, "proeq-design: cannot load %s\n", argv[2]);
		return 1;
	}
	if (strcmp(argv[3], "design") == 0 && argc == 8) {
		uint16_t params[4];
		for (int i = 0; i < 4; i++) params[i] = (uint16_t)strtol(argv[4 + i], NULL, 0);
		uint8_t record[12] = {0};
		uint32_t status = ((design_fn)pe_rva(img, RVA_DESIGN))(RATE, params, record);
		for (int i = 0; i < 11; i++) (void)printf("%02x", record[i]);
		(void)printf(" %u\n", status);
		return 0;
	}
	if (strcmp(argv[3], "analyse") == 0 && argc == 5 && strlen(argv[4]) == 22) {
		uint8_t record[12] = {0};
		for (int i = 0; i < 11; i++)
			if (hex_byte(argv[4] + (ptrdiff_t)2 * i, &record[i]) < 0) return 2;
		uint16_t params[4] = {0};
		int status = ((analyse_fn)pe_rva(img, RVA_ANALYSE))(RATE, record, params);
		(void)printf("%u %u %u %d %d\n", params[0], params[1], params[2], (int16_t)params[3], status);
		return 0;
	}
	(void)fprintf(stderr, "proeq-design: bad arguments\n");
	return 2;
}
