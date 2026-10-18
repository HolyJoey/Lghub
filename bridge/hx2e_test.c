/*
 * Offline check of the native DTS Headphone:X: feeds a noise burst into each 7.1 channel in turn
 * and prints the left/right energy that comes out, so you can see the virtual speakers placed
 * around you (front left louder on the left, rear right on the right, centre in the middle).
 *   hx2e_test DLL [HEADSET] [ROOM]
 */
#include "hx2e.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#define RATE 48000
#define BLOCK 480
#define BLOCKS 50

static const char *names[8] = {"front L", "front R", "centre", "LFE", "rear L", "rear R", "side L", "side R"};

int main(int argc, char **argv)
{
	if (argc < 2) {
		fprintf(stderr, "usage: %s DLL [HEADSET] [ROOM]\n", argv[0]);
		return 2;
	}
	hx2e *h = hx2e_open(argv[1], argc > 2 ? argv[2] : "PRO_X", RATE, 8);
	if (!h) {
		fprintf(stderr, "hx2e_open failed\n");
		return 1;
	}
	if (argc > 3 && hx2e_set(h, HX2E_ROOM, atoi(argv[3]))) fprintf(stderr, "room %s refused\n", argv[3]);
	static float in[BLOCK * 8], out[BLOCK * 2];
	srand(1);
	for (int ch = 0; ch < 8; ch++) {
		double l = 0, r = 0, peak = 0;
		int bad = 0;
		for (int b = 0; b < BLOCKS; b++) {
			for (int i = 0; i < BLOCK * 8; i++) in[i] = 0;
			for (int i = 0; i < BLOCK; i++) in[i * 8 + ch] = 0.25f * ((float)rand() / RAND_MAX * 2 - 1);
			if (hx2e_process(h, in, out, BLOCK)) bad++;
			for (int i = 0; i < BLOCK; i++) {
				float a = out[2 * i], c = out[2 * i + 1];
				if (!isfinite(a) || !isfinite(c)) bad++;
				l += a * a;
				r += c * c;
				if (fabsf(a) > peak) peak = fabsf(a);
				if (fabsf(c) > peak) peak = fabsf(c);
			}
		}
		printf("%-8s  L %6.1f dB  R %6.1f dB  peak %.3f%s\n", names[ch], 10 * log10(l + 1e-12),
		       10 * log10(r + 1e-12), peak, bad ? "  (errors)" : "");
	}
	hx2e_close(h);
	return 0;
}
