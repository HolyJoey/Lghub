/* micopt_test DLL PARAMS IN.f32 OUT.f32 — runs mono float32 48 kHz audio through MicOpt natively. */
#include "micopt.h"

#include <stdio.h>
#include <stdlib.h>
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
	FILE *in = fopen(argv[3], "rb"), *out = fopen(argv[4], "wb");
	if (!in || !out) { perror("open"); return 1; }
	int n = micopt_block(m);
	float *a = calloc(n, sizeof(float)), *b = calloc(n, sizeof(float));
	long blocks = 0;
	struct timespec t0, t1;
	clock_gettime(CLOCK_MONOTONIC, &t0);
	size_t got;
	while ((got = fread(a, sizeof(float), n, in)) > 0) {
		for (size_t i = got; i < (size_t)n; i++) a[i] = 0;
		if (micopt_process(m, a, b)) { fprintf(stderr, "process failed\n"); return 1; }
		fwrite(b, sizeof(float), n, out);
		blocks++;
	}
	clock_gettime(CLOCK_MONOTONIC, &t1);
	double secs = (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9;
	fprintf(stderr, "%ld blocks of %d frames in %.3f s (%.0fx realtime)\n", blocks, n, secs,
	        blocks * n / 48000.0 / secs);
	micopt_close(m);
	fclose(in);
	fclose(out);
	return 0;
}
