/* DTS Headphone:X 2.0 (Logitech's "HX2E" surround), called straight from Logitech's APO DLL. */
#ifndef HX2E_H
#define HX2E_H

typedef struct hx2e hx2e;

enum { HX2E_STATE = 0, HX2E_ROOM = 1, HX2E_STEREO = 2 };

/* headset: the DLL's tuning name, e.g. "PRO_X", "PRO_X_WIRELESS", "G733" (others get a default).
 * channels: 2 (stereo upmix), 6 (5.1) or 8 (7.1). Returns NULL if the DLL can't be used. */
hx2e *hx2e_open(const char *dll_path, const char *headset, int rate, int channels);
/* which: HX2E_STATE (0 off, 1 on), HX2E_ROOM (7.1/5.1 room), HX2E_STEREO (stereo mode). 0 = ok. */
int hx2e_set(hx2e *h, int which, int value);
/* in: frames x channels, interleaved. out: frames x 2, interleaved. 0 = ok. */
int hx2e_process(hx2e *h, const float *in, float *out, unsigned frames);
int hx2e_channels(const hx2e *h);
void hx2e_close(hx2e *h);

#endif
