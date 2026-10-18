/* Blue VO!CE 2 (DTS ClearVoice 2), called straight from Logitech's capture APO DLL. */
#ifndef BV2_H
#define BV2_H

typedef struct bv2 bv2;

/* rate: 44100/48000 (block 256), 88200/96000 (512) or 176400/192000 (1024). Mono. */
bv2 *bv2_open(const char *dll_path, int rate);
int bv2_block(const bv2 *b);
/* One APO property (pid, as in G HUB's property store) to the parameters; applied by bv2_apply. */
int bv2_set(bv2 *b, unsigned pid, float value);
int bv2_apply(bv2 *b);
/* One block, in and out of length bv2_block(). 0 = ok. */
int bv2_process(bv2 *b, const float *in, float *out);
void bv2_close(bv2 *b);

#endif
