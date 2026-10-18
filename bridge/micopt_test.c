/* micopt_test DLL PARAMS IN.f32 OUT.f32 — runs mono float32 48 kHz audio through MicOpt natively. */
#include "micopt.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

int main(int argc, char **argv)
{
	if (argc != 5) {
		fprintf(stderr, "usage: %s DLL PARAMS IN.f32 OUT.f32\n", argv[0]);
		return 2;
	}
	micopt *m = micopt_open(argv[1], 48000);
	if (!m) { fprintf(stderr, "cannot open MicOpt from %s\n", argv[1]); return 1; }
	micopt_load_params(m, argv[2]);
	FILE *in = fopen(argv[3], "rb");
	FILE *out = in ? fopen(argv[4], "wb") : NULL;
	int n = micopt_block(m);
	float *a = calloc((size_t)n, sizeof(float)), *b = calloc((size_t)n, sizeof(float));
	if (!in || !out || !a || !b) {
		perror("micopt_test");
		if (in) fclose(in);
		if (out) fclose(out);
		free(a);
		free(b);
		micopt_close(m);
		return 1;
	}
	long blocks = 0;
	struct timespec t0, t1;
	clock_gettime(CLOCK_MONOTONIC, &t0);
	for (;;) {
		size_t got = fread(a, sizeof(float), (size_t)n, in);
		if (got == 0) break;
		if (got < (size_t)n) memset(a + got, 0, ((size_t)n - got) * sizeof(float));
		if (micopt_process(m, a, b) || fwrite(b, sizeof(float), (size_t)n, out) != (size_t)n) {
			fprintf(stderr, "processing or writing failed\n");
			break;
		}
		blocks++;
		if (got < (size_t)n) break; /* end of input (or a read error) */
	}
	clock_gettime(CLOCK_MONOTONIC, &t1);
	double secs = (double)(t1.tv_sec - t0.tv_sec) + (double)(t1.tv_nsec - t0.tv_nsec) / 1e9;
	fprintf(stderr, "%ld blocks of %d frames in %.3f s (%.0fx realtime)\n", blocks, n, secs,
	        (double)blocks * n / 48000.0 / secs);
	micopt_close(m);
	free(a);
	free(b);
	fclose(in);
	return fclose(out) == 0 ? 0 : 1;
}
