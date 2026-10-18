#ifndef MICOPT_H
#define MICOPT_H

/* DTS MicOpt (Blue VO!CE 1) from Logitech's APO DLL, called natively. Mono only. */
typedef struct micopt micopt;

/* Loads the DLL and creates an instance with the APO's own defaults. NULL on failure. */
micopt *micopt_open(const char *dll_path, int rate);

/* Block size in frames: micopt_process always takes exactly this many. */
int micopt_block(const micopt *m);

/* Sample rate the instance was created for. */
int micopt_rate(const micopt *m);

/* 1 if MicOpt supports this sample rate (44.1/48/88.2/96/176.4/192 kHz). */
int micopt_supports_rate(int rate);

/* Sets one parameter by its APO name (e.g. "comp.ratio"). Returns 0 on success. */
int micopt_set(micopt *m, const char *name, float value);

/* Applies a "name value" params file (missing parameters keep their defaults). */
int micopt_load_params(micopt *m, const char *path);

/* Processes one block of micopt_block() frames; in and out may not overlap. */
int micopt_process(micopt *m, const float *in, float *out);

void micopt_close(micopt *m);

#endif
