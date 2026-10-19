/*
 * bluevoice-bridge — Logitech's Blue VO!CE (DTS MicOpt, from the G HUB APO DLL) as a native
 * PipeWire filter. No Wine: the DLL's DSP is loaded into this process (peloader.c) and called
 * from the audio thread (micopt.c).
 *
 *   mic --link--> [bluevoice_dsp:in] --MicOpt--> [bluevoice_dsp:out]
 *       --link--> "Blue VO!CE Microphone" (null-audio node, Audio/Source/Virtual)
 *
 * MicOpt works in fixed 256-frame blocks, so audio passes through two small FIFOs; the output FIFO
 * starts one block full, which makes the added delay exactly one block (plus MicOpt's own 128-frame
 * look-ahead): 8 ms at 48 kHz. The links are made by the caller (engine.py).
 *
 * Parameters come from a "name value" file, re-read whenever it changes. A change builds a new
 * MicOpt instance off the audio thread, warms it up on the live input, then crossfades to it.
 * If the graph's sample rate changes, an instance for the new rate replaces the old one outright.
 *
 * stderr: "ready ..." once, then "meter <in dBFS> <out dBFS>" every 100 ms (every second in silence).
 *
 * --engine bv2 runs Blue VO!CE 2 (DTS ClearVoice 2, bv2.c) from its own APO the same way; its
 * params file uses G HUB's setting names ("noiseReduction.sensitivity 6").
 *
 * Usage: bluevoice-bridge --dll APO.dll --params FILE [--engine micopt|bv2]
 */
#define _GNU_SOURCE
#include <math.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include <pipewire/pipewire.h>
#include <pipewire/filter.h>

#include "bv2.h"
#include "micopt.h"

#define RATE 48000                  /* until the graph tells us otherwise */
#define MAX_BLOCK 1024              /* MicOpt's block at 176.4/192 kHz */
#define FIFO_SIZE 16384             /* frames; power of two, > max quantum + block */
#define WARMUP_BLOCKS 19            /* ~100 ms */
#define XFADE_BLOCKS 6              /* ~30 ms */

struct port { void *unused; };

/* The DSP behind the filter: both work on fixed mono blocks and are rebuilt to change parameters. */
struct dsp {
	void *(*open)(const char *dll_path, int rate);
	int (*block)(const void *inst);
	int (*supports_rate)(int rate);
	int (*load_params)(void *inst, const char *path);
	int (*process)(void *inst, const float *in, float *out);
	void (*close)(void *inst);
};

static void *mo_open(const char *dll, int rate) { return micopt_open(dll, rate); }
static int mo_block(const void *m) { return micopt_block(m); }
static int mo_load(void *m, const char *path) { return micopt_load_params(m, path); }
static int mo_process(void *m, const float *in, float *out) { return micopt_process(m, in, out); }
static void mo_close(void *m) { micopt_close(m); }
static const struct dsp MICOPT = {mo_open, mo_block, micopt_supports_rate, mo_load, mo_process, mo_close};

static void *cv_open(const char *dll, int rate) { return bv2_open(dll, rate); }
static int cv_block(const void *b) { return bv2_block(b); }
static int cv_load(void *b, const char *path) { return bv2_load_params(b, path); }
static int cv_process(void *b, const float *in, float *out) { return bv2_process(b, in, out); }
static void cv_close(void *b) { bv2_close(b); }
static const struct dsp BV2 = {cv_open, cv_block, bv2_supports_rate, cv_load, cv_process, cv_close};

struct fifo {
	float data[FIFO_SIZE];
	uint32_t read, write;           /* free-running; only touched by the audio thread */
};

static uint32_t fifo_fill(const struct fifo *f) { return f->write - f->read; }
static void fifo_push(struct fifo *f, const float *x, uint32_t n)
{
	for (uint32_t i = 0; i < n; i++) f->data[(f->write + i) % FIFO_SIZE] = x[i];
	f->write += n;
}
static void fifo_pop(struct fifo *f, float *x, uint32_t n)
{
	for (uint32_t i = 0; i < n; i++) x[i] = f->data[(f->read + i) % FIFO_SIZE];
	f->read += n;
}

struct bridge {
	struct pw_main_loop *loop;
	struct pw_context *context;
	struct pw_core *core;
	struct pw_filter *filter;
	struct port *in_port, *out_port;
	struct pw_proxy *virtual_mic;
	const char *dll_path, *params_path;
	const struct dsp *dsp;
	int rate;                       /* main thread: rate of the newest instance */
	struct timespec params_mtime;

	/* audio-thread state */
	void *current;
	_Atomic(void *) pending;        /* main -> audio: next instance */
	_Atomic(void *) retired;        /* audio -> main: instance to free */
	void *next;
	int next_age;
	int block;
	_Atomic int graph_rate;         /* audio -> main: rate the graph runs at */
	struct fifo in_fifo, out_fifo;
	float *blk_in, *blk_out, *blk_next;

	/* meters: peak power per 100 ms window, as float bits */
	_Atomic uint32_t meter_in, meter_out;
};

static struct bridge B;

static float power(const float *x, uint32_t n)
{
	float acc = 0;
	for (uint32_t i = 0; i < n; i++) acc += x[i] * x[i];
	return acc / (float)n;
}

static void meter_max(_Atomic uint32_t *slot, float value)
{
	uint32_t old = atomic_load(slot), bits;
	float cur;
	do {
		memcpy(&cur, &old, 4);
		if (value <= cur) return;
		memcpy(&bits, &value, 4);
	} while (!atomic_compare_exchange_weak(slot, &old, bits));
}

/* One DSP block, crossfading to a new instance while one is pending. */
static void process_block(struct bridge *b)
{
	b->dsp->process(b->current, b->blk_in, b->blk_out);
	if (!b->next) {
		void *p = atomic_load(&b->pending);
		if (p && b->dsp->block(p) == b->block && atomic_compare_exchange_strong(&b->pending, &p, NULL)) {
			b->next = p;
			b->next_age = 0;
		}
	}
	if (!b->next) return;
	b->dsp->process(b->next, b->blk_in, b->blk_next);
	int k = b->next_age - WARMUP_BLOCKS;
	if (k >= 0) {
		for (int i = 0; i < b->block; i++) {
			float g = (float)(k * b->block + i) / (float)(XFADE_BLOCKS * b->block);
			b->blk_out[i] = (1.0f - g) * b->blk_out[i] + g * b->blk_next[i];
		}
		if (k + 1 >= XFADE_BLOCKS) {
			void *old = b->current;
			b->current = b->next;
			b->next = NULL;
			void *expect = NULL;
			if (!atomic_compare_exchange_strong(&b->retired, &expect, old))
				b->dsp->close(old); /* the main thread hasn't collected the last one; rare */
		}
	}
	b->next_age++;
}

static void on_process(void *data, struct spa_io_position *position)
{
	struct bridge *b = data;
	uint32_t n = (uint32_t)position->clock.duration; /* a quantum, far below 2^32 */
	float *in = pw_filter_get_dsp_buffer(b->in_port, n);
	float *out = pw_filter_get_dsp_buffer(b->out_port, n);
	if (!out) return;
	if (n + MAX_BLOCK > FIFO_SIZE / 2) { memset(out, 0, n * sizeof(float)); return; }
	atomic_store(&b->graph_rate, (int)position->clock.rate.denom);

	/* A new instance for a different sample rate can't be crossfaded (other block size): swap it
	 * in directly and restart the FIFOs. */
	void *p = atomic_load(&b->pending);
	if (p && !b->next && b->dsp->block(p) != b->block && atomic_compare_exchange_strong(&b->pending, &p, NULL)) {
		void *old = b->current, *expect = NULL;
		b->current = p;
		b->block = b->dsp->block(p);
		b->in_fifo.read = b->in_fifo.write;
		b->out_fifo.read = 0;
		b->out_fifo.write = b->block;
		memset(b->out_fifo.data, 0, b->block * sizeof(float));
		if (!atomic_compare_exchange_strong(&b->retired, &expect, old)) b->dsp->close(old);
	}

	if (in) {
		fifo_push(&b->in_fifo, in, n);
		meter_max(&b->meter_in, power(in, n));
	} else {
		static const float zeros[1024];
		for (uint32_t left = n; left;) {
			uint32_t k = left < 1024 ? left : 1024;
			fifo_push(&b->in_fifo, zeros, k);
			left -= k;
		}
	}
	while (fifo_fill(&b->in_fifo) >= (uint32_t)b->block) {
		fifo_pop(&b->in_fifo, b->blk_in, b->block);
		process_block(b);
		fifo_push(&b->out_fifo, b->blk_out, b->block);
	}
	fifo_pop(&b->out_fifo, out, n);
	meter_max(&b->meter_out, power(out, n));
}

static void on_state(void *data, enum pw_filter_state old, enum pw_filter_state state, const char *error)
{
	(void)data;
	(void)old;
	fprintf(stderr, "bridge: filter %s%s%s\n", pw_filter_state_as_string(state), error ? ": " : "", error ? error : "");
}

static const struct pw_filter_events filter_events = {
	PW_VERSION_FILTER_EVENTS, .state_changed = on_state, .process = on_process,
};

static void *new_instance(struct bridge *b, int rate)
{
	void *m = b->dsp->open(b->dll_path, rate);
	if (m && b->dsp->load_params(m, b->params_path) < 0) fprintf(stderr, "bridge: cannot read %s\n", b->params_path);
	return m;
}

static int params_changed(struct bridge *b)
{
	struct stat st;
	if (stat(b->params_path, &st) < 0) return 0;
	if (st.st_mtim.tv_sec == b->params_mtime.tv_sec && st.st_mtim.tv_nsec == b->params_mtime.tv_nsec) return 0;
	b->params_mtime = st.st_mtim;
	return 1;
}

static double to_db(_Atomic uint32_t *slot)
{
	uint32_t bits = atomic_exchange(slot, 0);
	float p;
	memcpy(&p, &bits, 4);
	return p > 1e-12f ? 10.0 * log10((double)p) : -120.0;
}

/* Every 100 ms: meters, parameter changes, and freeing retired instances. */
static void on_timer(void *data, uint64_t expirations)
{
	(void)expirations;
	struct bridge *b = data;
	void *old = atomic_exchange(&b->retired, NULL);
	if (old) b->dsp->close(old);
	int rate = atomic_load(&b->graph_rate);
	int rate_changed = rate && rate != b->rate && b->dsp->supports_rate(rate);
	if ((rate_changed || params_changed(b)) && !atomic_load(&b->pending)) {
		if (rate_changed) b->rate = rate;
		void *m = new_instance(b, b->rate);
		if (m) {
			atomic_store(&b->pending, m);
			fprintf(stderr, rate_changed ? "sample rate now %d\n" : "reloaded parameters\n", b->rate);
		}
	}
	double in_db = to_db(&b->meter_in), out_db = to_db(&b->meter_out);
	static int quiet_ticks;
	/* Silence is reported once a second, sound every 100 ms: an idle engine needn't wake 10x/s. */
	if (in_db > -119.0 || out_db > -119.0 || ++quiet_ticks >= 10) {
		quiet_ticks = 0;
		fprintf(stderr, "meter %.1f %.1f\n", in_db, out_db);
	}
}

static void on_signal(void *data, int sig)
{
	(void)sig;
	pw_main_loop_quit(((struct bridge *)data)->loop);
}

int main(int argc, char **argv)
{
	struct bridge *b = &B;
	const char *engine = "micopt";
	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--dll") && i + 1 < argc) b->dll_path = argv[++i];
		else if (!strcmp(argv[i], "--params") && i + 1 < argc) b->params_path = argv[++i];
		else if (!strcmp(argv[i], "--engine") && i + 1 < argc) engine = argv[++i];
		else if (!strcmp(argv[i], "--max-latency") && i + 1 < argc) i++; /* accepted for compatibility */
	}
	b->dsp = !strcmp(engine, "bv2") ? &BV2 : !strcmp(engine, "micopt") ? &MICOPT : NULL;
	if (!b->dll_path || !b->params_path || !b->dsp) {
		fprintf(stderr, "usage: %s --dll APO.dll --params FILE [--engine micopt|bv2]\n", argv[0]);
		return 2;
	}

	params_changed(b);
	b->rate = RATE;
	b->current = new_instance(b, b->rate);
	if (!b->current) {
		fprintf(stderr, "bridge: cannot load Blue VO!CE from %s\n", b->dll_path);
		return 1;
	}
	b->block = b->dsp->block(b->current);
	b->blk_in = calloc(MAX_BLOCK, sizeof(float));
	b->blk_out = calloc(MAX_BLOCK, sizeof(float));
	b->blk_next = calloc(MAX_BLOCK, sizeof(float));
	b->out_fifo.write = b->block; /* one block of silence: the fixed delay that keeps output flowing */

	pw_init(&argc, &argv);
	b->loop = pw_main_loop_new(NULL);
	struct pw_loop *loop = pw_main_loop_get_loop(b->loop);
	pw_loop_add_signal(loop, SIGINT, on_signal, b);
	pw_loop_add_signal(loop, SIGTERM, on_signal, b);
	b->context = pw_context_new(loop, NULL, 0);
	b->core = pw_context_connect(b->context, NULL, 0);
	if (!b->core) { fprintf(stderr, "bridge: cannot connect to PipeWire\n"); return 1; }

	/* The virtual microphone apps record from. Not lingering: it goes away with us. */
	struct pw_properties *mic = pw_properties_new(
		"factory.name", "support.null-audio-sink", PW_KEY_NODE_NAME, "bluevoice_mic",
		PW_KEY_NODE_DESCRIPTION, "Blue VO!CE Microphone", PW_KEY_MEDIA_CLASS, "Audio/Source/Virtual",
		"audio.position", "[ MONO ]", "audio.rate", "48000", NULL);
	b->virtual_mic = pw_core_create_object(b->core, "adapter", PW_TYPE_INTERFACE_Node, PW_VERSION_NODE,
	                                       &mic->dict, 0);
	pw_properties_free(mic);

	b->filter = pw_filter_new_simple(loop, "bluevoice-dsp",
		pw_properties_new(PW_KEY_MEDIA_TYPE, "Audio", PW_KEY_MEDIA_CATEGORY, "Filter",
		                  PW_KEY_MEDIA_ROLE, "DSP", PW_KEY_NODE_NAME, "bluevoice_dsp",
		                  PW_KEY_NODE_DESCRIPTION, "Blue VO!CE processing", PW_KEY_APP_NAME, "Blue VO!CE",
		                  /* No node.latency: forcing a small quantum would make the whole audio graph,
		                   * games included, wake more often. The FIFOs handle any quantum. */
		                  PW_KEY_NODE_AUTOCONNECT, "false", NULL),
		&filter_events, b);
	b->in_port = pw_filter_add_port(b->filter, PW_DIRECTION_INPUT, PW_FILTER_PORT_FLAG_MAP_BUFFERS,
		sizeof(struct port), pw_properties_new(PW_KEY_FORMAT_DSP, "32 bit float mono audio",
		                                       PW_KEY_PORT_NAME, "in", NULL), NULL, 0);
	b->out_port = pw_filter_add_port(b->filter, PW_DIRECTION_OUTPUT, PW_FILTER_PORT_FLAG_MAP_BUFFERS,
		sizeof(struct port), pw_properties_new(PW_KEY_FORMAT_DSP, "32 bit float mono audio",
		                                       PW_KEY_PORT_NAME, "out", NULL), NULL, 0);
	if (pw_filter_connect(b->filter, PW_FILTER_FLAG_RT_PROCESS, NULL, 0) < 0) {
		fprintf(stderr, "bridge: cannot connect filter\n");
		return 1;
	}

	struct spa_source *timer = pw_loop_add_timer(loop, on_timer, b);
	struct timespec period = {0, 100L * 1000 * 1000};
	pw_loop_update_timer(loop, timer, &period, &period, false);

	fprintf(stderr, "ready rate=%d block=%d (native, no Wine)\n", RATE, b->block);
	pw_main_loop_run(b->loop);

	fprintf(stderr, "bridge: stopping\n");
	pw_filter_destroy(b->filter);
	pw_proxy_destroy(b->virtual_mic);
	pw_core_disconnect(b->core);
	pw_context_destroy(b->context);
	pw_main_loop_destroy(b->loop);
	pw_deinit();
	b->dsp->close(b->current);
	b->dsp->close(b->next);
	b->dsp->close(atomic_load(&b->pending));
	b->dsp->close(atomic_load(&b->retired));
	return 0;
}
