/*
 * surround-bridge — G HUB's DTS Headphone:X 2.0 virtual surround as a PipeWire output. No Wine:
 * Logitech's playback effect DLL is loaded into this process (peloader.c, hx2e.c).
 *
 *   apps --> "<headset> (Surround 7.1)" (null-audio sink, 8 channels)
 *        --monitor--> [lghub_surround_dsp:in_FL..in_SR] --DTS--> [out_FL, out_FR] --> headset
 *
 * The links are made by the caller (engine.py). Any quantum works: the DSP takes whatever
 * number of frames it is given. At sample rates DTS has no tuning for (only 44.1 and 48 kHz),
 * the channels are simply mixed down to stereo.
 *
 * Settings come from a "name value" file, re-read when it changes:
 *   state 0|1        DTS on or off (off: the APO's own pass-through downmix)
 *   room N           DTS room
 *   gain_FL ... gain_SR   per-channel volume, linear (G HUB's default is 1.1)
 *   eq 0|1, eq_1 ... eq_10   the headset equalizer's gains in dB, applied after DTS when on (the
 *                    same filters as the equalizer's PipeWire filter-chain, so one sound either way)
 *
 * Usage: surround-bridge --dll APO.dll --headset NAME --settings FILE --description TEXT
 */
#define _GNU_SOURCE  /* NOLINT(bugprone-reserved-identifier,cert-dcl37-c,cert-dcl51-cpp): glibc's feature switch */
#include <math.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include <pipewire/pipewire.h>
#include <pipewire/filter.h>

#include "hx2e.h"

#define CHANNELS 8
#define MAX_FRAMES 8192
#define DEFAULT_GAIN 1.1f
#define BANDS 10
#define EQ_Q 1.41f

static const float band_freq[BANDS] = {32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000};

static const char *const positions[CHANNELS] = {"FL", "FR", "FC", "LFE", "RL", "RR", "SL", "SR"};
/* Plain 7.1 -> stereo downmix for rates DTS can't do: centre and surrounds at -3 dB. */
static const float down_l[CHANNELS] = {1, 0, 0.707f, 0.5f, 0.707f, 0, 0.707f, 0};
static const float down_r[CHANNELS] = {0, 1, 0.707f, 0.5f, 0, 0.707f, 0, 0.707f};

struct port { void *unused; };

struct settings {
	int state, room, eq;
	float gain[CHANNELS];
	float eq_db[BANDS];
};

/* One biquad, Web Audio's formulas (what PipeWire's bq_lowshelf / bq_peaking / bq_highshelf use). */
struct biquad {
	float b0, b1, b2, a1, a2;
	float z1[2], z2[2];               /* per output channel */
};

enum { LOWSHELF, PEAKING, HIGHSHELF };

static void biquad_set(struct biquad *q, int type, float freq, float gain_db, int rate)
{
	double A = pow(10.0, gain_db / 40.0), w0 = 2.0 * M_PI * freq / rate, k = cos(w0), sn = sin(w0);
	double b0, b1, b2, a0, a1, a2;
	if (type == PEAKING) {
		double alpha = sn / (2.0 * EQ_Q);
		b0 = 1 + alpha * A; b1 = -2 * k; b2 = 1 - alpha * A;
		a0 = 1 + alpha / A; a1 = -2 * k; a2 = 1 - alpha / A;
	} else {
		double alpha = 0.5 * sn * sqrt(2.0), k2 = 2 * sqrt(A) * alpha;   /* shelf slope 1 */
		if (type == LOWSHELF) {
			b0 = A * ((A + 1) - (A - 1) * k + k2); b1 = 2 * A * ((A - 1) - (A + 1) * k);
			b2 = A * ((A + 1) - (A - 1) * k - k2);
			a0 = (A + 1) + (A - 1) * k + k2; a1 = -2 * ((A - 1) + (A + 1) * k); a2 = (A + 1) + (A - 1) * k - k2;
		} else {
			b0 = A * ((A + 1) + (A - 1) * k + k2); b1 = -2 * A * ((A - 1) + (A + 1) * k);
			b2 = A * ((A + 1) + (A - 1) * k - k2);
			a0 = (A + 1) - (A - 1) * k + k2; a1 = 2 * ((A - 1) - (A + 1) * k); a2 = (A + 1) - (A - 1) * k - k2;
		}
	}
	q->b0 = (float)(b0 / a0); q->b1 = (float)(b1 / a0); q->b2 = (float)(b2 / a0);
	q->a1 = (float)(a1 / a0); q->a2 = (float)(a2 / a0);
}

static void biquad_run(struct biquad *q, int ch, float *x, uint32_t n)
{
	float z1 = q->z1[ch], z2 = q->z2[ch];
	for (uint32_t i = 0; i < n; i++) {   /* transposed direct form II */
		float in = x[i], out = q->b0 * in + z1;
		z1 = q->b1 * in - q->a1 * out + z2;
		z2 = q->b2 * in - q->a2 * out;
		x[i] = out;
	}
	q->z1[ch] = z1;
	q->z2[ch] = z2;
}

struct bridge {
	struct pw_main_loop *loop;
	struct pw_context *context;
	struct pw_core *core;
	struct pw_filter *filter;
	struct port *in[CHANNELS], *out[2];
	struct pw_proxy *sink;
	const char *dll_path, *headset, *settings_path, *description;
	struct timespec settings_mtime;
	int rate;                         /* main thread: rate of the newest instance */

	/* main -> audio */
	_Atomic(hx2e *) pending;
	_Atomic(hx2e *) retired;
	_Atomic int settings_serial;
	struct settings shared;           /* written by main before bumping settings_serial */

	/* audio thread */
	struct biquad eq[BANDS];
	int eq_rate;
	hx2e *current;
	int applied_serial;
	struct settings live;
	_Atomic int graph_rate;
	_Atomic uint32_t meter_in, meter_out;   /* peak power per window, as float bits */
	float interleaved[MAX_FRAMES * CHANNELS], stereo[MAX_FRAMES * 2];
};

static struct bridge B;

static void downmix(const struct bridge *b, float *const *in, float *l, float *r, uint32_t n)
{
	for (uint32_t i = 0; i < n; i++) {
		float a = 0, c = 0;
		for (int ch = 0; ch < CHANNELS; ch++) {
			float x = in[ch] ? in[ch][i] * b->live.gain[ch] : 0;
			a += down_l[ch] * x;
			c += down_r[ch] * x;
		}
		l[i] = a;
		r[i] = c;
	}
}

static void meter_max(_Atomic uint32_t *slot, const float *x, uint32_t n)
{
	float p = 0;
	for (uint32_t i = 0; i < n; i++) p += x[i] * x[i];
	p /= (float)(n ? n : 1);
	uint32_t old = atomic_load(slot), bits;
	float cur;
	do {
		memcpy(&cur, &old, 4);
		if (p <= cur) return;
		memcpy(&bits, &p, 4);
	} while (!atomic_compare_exchange_weak(slot, &old, bits));
}

static double to_db(_Atomic uint32_t *slot)
{
	uint32_t bits = atomic_exchange(slot, 0);
	float p;
	memcpy(&p, &bits, 4);
	return p > 1e-12f ? 10.0 * log10((double)p) : -120.0;
}

static void set_eq(struct bridge *b, int rate)
{
	for (int i = 0; i < BANDS; i++)
		biquad_set(&b->eq[i], i == 0 ? LOWSHELF : i == BANDS - 1 ? HIGHSHELF : PEAKING, band_freq[i],
		           b->live.eq_db[i], rate);
	b->eq_rate = rate;
}

static void run_eq(struct bridge *b, float *l, float *r, uint32_t n, int rate)
{
	if (!b->live.eq) return;
	if (rate != b->eq_rate) set_eq(b, rate);
	for (int i = 0; i < BANDS; i++) {
		biquad_run(&b->eq[i], 0, l, n);
		biquad_run(&b->eq[i], 1, r, n);
	}
}

static void apply_settings(struct bridge *b)
{
	int serial = atomic_load(&b->settings_serial);
	if (serial == b->applied_serial) return;
	b->applied_serial = serial;
	struct settings s = b->shared;
	b->eq_rate = 0;                   /* recompute the filters (keeps their state: no click) */
	if (b->current && s.state != b->live.state) hx2e_set(b->current, HX2E_STATE, s.state);
	if (b->current && s.room != b->live.room) hx2e_set(b->current, HX2E_ROOM, s.room);
	b->live = s;
}

static void on_process(void *data, struct spa_io_position *position)
{
	struct bridge *b = data;
	uint32_t n = (uint32_t)position->clock.duration;
	float *l = pw_filter_get_dsp_buffer(b->out[0], n), *r = pw_filter_get_dsp_buffer(b->out[1], n);
	if (!l || !r) return;
	atomic_store(&b->graph_rate, (int)position->clock.rate.denom);

	hx2e *p = atomic_load(&b->pending);
	if (p && atomic_compare_exchange_strong(&b->pending, &p, NULL)) {
		hx2e *old = b->current, *expect = NULL;
		b->current = p;
		b->applied_serial = -1;       /* apply the settings to the new instance */
		b->live.state = 1;
		b->live.room = 0;                 /* the DLL's own start value; apply_settings sets ours */
		if (old && !atomic_compare_exchange_strong(&b->retired, &expect, old)) hx2e_close(old);
	}
	apply_settings(b);

	float *in[CHANNELS];
	for (int ch = 0; ch < CHANNELS; ch++) in[ch] = pw_filter_get_dsp_buffer(b->in[ch], n);
	for (int ch = 0; ch < CHANNELS; ch++)
		if (in[ch]) meter_max(&b->meter_in, in[ch], n);
	int rate_ok = (int)position->clock.rate.denom == b->rate;
	int rate = (int)position->clock.rate.denom;
	if (!b->current || !rate_ok || n > MAX_FRAMES) {
		downmix(b, in, l, r, n);
		run_eq(b, l, r, n, rate);
		return;
	}
	for (uint32_t i = 0; i < n; i++)
		for (int ch = 0; ch < CHANNELS; ch++)
			b->interleaved[i * CHANNELS + ch] = in[ch] ? in[ch][i] * b->live.gain[ch] : 0;
	if (hx2e_process(b->current, b->interleaved, b->stereo, n)) {
		downmix(b, in, l, r, n);
		run_eq(b, l, r, n, rate);
		return;
	}
	for (uint32_t i = 0; i < n; i++) {
		l[i] = b->stereo[2 * (size_t)i];
		r[i] = b->stereo[2 * (size_t)i + 1];
	}
	run_eq(b, l, r, n, rate);
	meter_max(&b->meter_out, l, n);
}

static void on_state(void *data, enum pw_filter_state old, enum pw_filter_state state, const char *error)
{
	(void)data;
	(void)old;
	(void)fprintf(stderr, "surround: filter %s%s%s\n", pw_filter_state_as_string(state), error ? ": " : "", error ? error : "");
}

static const struct pw_filter_events filter_events = {
	PW_VERSION_FILTER_EVENTS, .state_changed = on_state, .process = on_process,
};

static void read_settings(struct bridge *b)
{
	struct settings s = {.state = 1, .room = 1};   /* G HUB's default room: Gaming */
	for (int ch = 0; ch < CHANNELS; ch++) s.gain[ch] = DEFAULT_GAIN;
	FILE *f = fopen(b->settings_path, "r");
	if (f) {
		char line[128];
		while (fgets(line, sizeof line, f)) {
			char *name = strtok(line, " \t\r\n"), *text = strtok(NULL, " \t\r\n"), *end;
			if (!name || !text || name[0] == '#') continue;
			float v = strtof(text, &end);
			if (end == text || *end) continue;
			if (!strcmp(name, "state")) s.state = v != 0;
			else if (!strcmp(name, "room")) s.room = (int)v;
			else if (!strcmp(name, "eq")) s.eq = v != 0;
			else if (!strncmp(name, "eq_", 3)) {
				char *after;
				long band = strtol(name + 3, &after, 10);
				if (after != name + 3 && !*after && band >= 1 && band <= BANDS)
					s.eq_db[band - 1] = v < -24 ? -24 : v > 24 ? 24 : v;
			}
			for (int ch = 0; ch < CHANNELS; ch++)
				if (!strncmp(name, "gain_", 5) && !strcmp(name + 5, positions[ch])) s.gain[ch] = v < 0 ? 0 : v > 4 ? 4 : v;
		}
		(void)fclose(f);
	}
	b->shared = s;
	atomic_fetch_add(&b->settings_serial, 1);
}

static int settings_changed(struct bridge *b)
{
	struct stat st;
	if (stat(b->settings_path, &st) < 0) return 0;
	if (st.st_mtim.tv_sec == b->settings_mtime.tv_sec && st.st_mtim.tv_nsec == b->settings_mtime.tv_nsec) return 0;
	b->settings_mtime = st.st_mtim;
	return 1;
}

/* Every 200 ms: settings, sample-rate changes, freeing retired instances. */
static void on_timer(void *data, uint64_t expirations)
{
	(void)expirations;
	struct bridge *b = data;
	hx2e *old = atomic_exchange(&b->retired, NULL);
	if (old) hx2e_close(old);
	(void)fprintf(stderr, "meter %.1f %.1f\n", to_db(&b->meter_in), to_db(&b->meter_out));
	if (settings_changed(b)) {
		read_settings(b);
		(void)fprintf(stderr, "surround: settings reloaded\n");
	}
	int rate = atomic_load(&b->graph_rate);
	if (rate && rate != b->rate && (rate == 44100 || rate == 48000) && !atomic_load(&b->pending)) {
		hx2e *h = hx2e_open(b->dll_path, b->headset, rate, CHANNELS);
		if (h) {
			b->rate = rate;
			atomic_store(&b->pending, h);
			(void)fprintf(stderr, "surround: sample rate now %d\n", rate);
		}
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
	b->headset = "PRO_X";
	b->description = "Headset (Surround 7.1)";
	for (int i = 1; i + 1 < argc; i++) {
		if (!strcmp(argv[i], "--dll")) b->dll_path = argv[++i];
		else if (!strcmp(argv[i], "--headset")) b->headset = argv[++i];
		else if (!strcmp(argv[i], "--settings")) b->settings_path = argv[++i];
		else if (!strcmp(argv[i], "--description")) b->description = argv[++i];
	}
	if (!b->dll_path || !b->settings_path) {
		(void)fprintf(stderr, "usage: %s --dll APO.dll --headset NAME --settings FILE --description TEXT\n", argv[0]);
		return 2;
	}
	settings_changed(b);
	read_settings(b);
	b->rate = 48000;
	b->current = hx2e_open(b->dll_path, b->headset, b->rate, CHANNELS);
	if (!b->current) {
		(void)fprintf(stderr, "surround: cannot load DTS Headphone:X from %s\n", b->dll_path);
		return 1;
	}
	b->applied_serial = -1;
	b->live.state = 1;

	pw_init(&argc, &argv);
	b->loop = pw_main_loop_new(NULL);
	struct pw_loop *loop = pw_main_loop_get_loop(b->loop);
	pw_loop_add_signal(loop, SIGINT, on_signal, b);
	pw_loop_add_signal(loop, SIGTERM, on_signal, b);
	b->context = pw_context_new(loop, NULL, 0);
	b->core = pw_context_connect(b->context, NULL, 0);
	if (!b->core) { (void)fprintf(stderr, "surround: cannot connect to PipeWire\n"); return 1; }

	/* The 7.1 output apps play into; it goes away with us. */
	struct pw_properties *sink = pw_properties_new(
		"factory.name", "support.null-audio-sink", PW_KEY_NODE_NAME, "lghub_surround",
		PW_KEY_NODE_DESCRIPTION, b->description, PW_KEY_MEDIA_CLASS, "Audio/Sink",
		"audio.position", "[ FL FR FC LFE RL RR SL SR ]", "monitor.channel-volumes", "true",
		/* follow the headset's clock instead of running its own */
		"node.driver", "false", NULL);
	b->sink = pw_core_create_object(b->core, "adapter", PW_TYPE_INTERFACE_Node, PW_VERSION_NODE, &sink->dict, 0);
	pw_properties_free(sink);

	b->filter = pw_filter_new_simple(loop, "lghub-surround-dsp",
		pw_properties_new(PW_KEY_MEDIA_TYPE, "Audio", PW_KEY_MEDIA_CATEGORY, "Filter",
		                  PW_KEY_MEDIA_ROLE, "DSP", PW_KEY_NODE_NAME, "lghub_surround_dsp",
		                  PW_KEY_NODE_DESCRIPTION, "DTS Headphone:X processing", PW_KEY_APP_NAME, "Lghub",
		                  PW_KEY_NODE_AUTOCONNECT, "false", NULL),
		&filter_events, b);
	char name[16];
	for (int ch = 0; ch < CHANNELS; ch++) {
		(void)snprintf(name, sizeof name, "in_%s", positions[ch]);
		b->in[ch] = pw_filter_add_port(b->filter, PW_DIRECTION_INPUT, PW_FILTER_PORT_FLAG_MAP_BUFFERS,
			sizeof(struct port), pw_properties_new(PW_KEY_FORMAT_DSP, "32 bit float mono audio",
			                                       PW_KEY_PORT_NAME, name, PW_KEY_AUDIO_CHANNEL, positions[ch], NULL),
			NULL, 0);
	}
	for (int ch = 0; ch < 2; ch++) {
		(void)snprintf(name, sizeof name, "out_%s", positions[ch]);
		b->out[ch] = pw_filter_add_port(b->filter, PW_DIRECTION_OUTPUT, PW_FILTER_PORT_FLAG_MAP_BUFFERS,
			sizeof(struct port), pw_properties_new(PW_KEY_FORMAT_DSP, "32 bit float mono audio",
			                                       PW_KEY_PORT_NAME, name, PW_KEY_AUDIO_CHANNEL, positions[ch], NULL),
			NULL, 0);
	}
	if (pw_filter_connect(b->filter, PW_FILTER_FLAG_RT_PROCESS, NULL, 0) < 0) {
		(void)fprintf(stderr, "surround: cannot connect filter\n");
		return 1;
	}
	struct spa_source *timer = pw_loop_add_timer(loop, on_timer, b);
	struct timespec period = {0, 200L * 1000 * 1000};
	pw_loop_update_timer(loop, timer, &period, &period, false);

	(void)fprintf(stderr, "ready headset=%s\n", b->headset);
	pw_main_loop_run(b->loop);

	pw_filter_destroy(b->filter);
	pw_proxy_destroy(b->sink);
	pw_core_disconnect(b->core);
	pw_context_destroy(b->context);
	pw_main_loop_destroy(b->loop);
	pw_deinit();
	hx2e_close(b->current);
	hx2e_close(atomic_load(&b->pending));
	hx2e_close(atomic_load(&b->retired));
	return 0;
}
