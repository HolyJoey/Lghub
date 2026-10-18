/*
 * bluevoice-bridge — connects a real microphone to Logitech's Blue VO!CE APO (running in
 * bluevoice_host.exe under Wine) and publishes the result as a virtual PipeWire microphone.
 *
 *   mic --link--> [bluevoice_dsp:in] --> host stdin --APO--> host stdout --ring--> [bluevoice_dsp:out]
 *       --link--> "Blue VO!CE Microphone" (null-audio node, Audio/Source/Virtual)
 *
 * The filter has plain DSP ports, so it needs no session-manager configuration; the virtual
 * microphone is a device-like node owned by this process (it disappears when we exit). Links are
 * made by the caller with pw-link (see bluevoice-engine), which keeps device selection out of here.
 * Latency through the ring is capped: anything beyond --max-latency is dropped.
 *
 * Usage: bluevoice-bridge [--max-latency MS] -- HOST_COMMAND...
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

#include <pipewire/pipewire.h>
#include <pipewire/filter.h>
#include <spa/utils/ringbuffer.h>

#define RATE 48000
#define RING_SIZE (1u << 16) /* floats; must be a power of two (~1.4 s) */

struct port { void *unused; };

struct bridge {
    struct pw_main_loop *loop;
    struct pw_context *context;
    struct pw_core *core;
    struct pw_filter *filter;
    struct port *in_port, *out_port;
    struct pw_proxy *virtual_mic;

    int host_in, host_out; /* our ends of the host's stdin / stdout */
    pid_t host_pid;
    pthread_t reader;

    struct spa_ringbuffer ring;
    float ring_data[RING_SIZE];
    uint32_t max_latency; /* frames */
    unsigned long dropped_in, dropped_out, underruns;
};

static struct bridge B;

/* Realtime: mic block -> host (never blocks), ring -> virtual microphone. */
static void on_process(void *data, struct spa_io_position *position)
{
    struct bridge *b = data;
    uint32_t n = position->clock.duration;
    float *in = pw_filter_get_dsp_buffer(b->in_port, n);
    float *out = pw_filter_get_dsp_buffer(b->out_port, n);

    if (in) {
        ssize_t w = write(b->host_in, in, n * sizeof(float));
        if (w < (ssize_t)(n * sizeof(float))) b->dropped_in++;
    }
    if (!out) return;

    uint32_t index;
    int32_t avail = spa_ringbuffer_get_read_index(&b->ring, &index);
    if (avail > (int32_t)(b->max_latency + n)) {
        /* Too much buffered: skip ahead so delay stays bounded. */
        uint32_t skip = avail - b->max_latency;
        index += skip;
        avail -= skip;
        b->dropped_out += skip;
    }
    uint32_t got = avail < (int32_t)n ? (avail > 0 ? (uint32_t)avail : 0) : n;
    spa_ringbuffer_read_data(&b->ring, b->ring_data, RING_SIZE * sizeof(float),
                             (index % RING_SIZE) * sizeof(float), out, got * sizeof(float));
    spa_ringbuffer_read_update(&b->ring, index + got);
    if (got < n) {
        memset(out + got, 0, (n - got) * sizeof(float));
        b->underruns++;
    }
}

static void on_state(void *data, enum pw_filter_state old, enum pw_filter_state state, const char *error)
{
    fprintf(stderr, "bridge: filter %s%s%s\n", pw_filter_state_as_string(state), error ? ": " : "", error ? error : "");
}

static const struct pw_filter_events filter_events = {
    PW_VERSION_FILTER_EVENTS, .state_changed = on_state, .process = on_process,
};

/* Host -> ring, on an ordinary thread (blocking reads are fine here). */
static void *reader_main(void *data)
{
    struct bridge *b = data;
    float tmp[1024];
    for (;;) {
        ssize_t r = read(b->host_out, tmp, sizeof tmp);
        if (r <= 0) {
            if (r < 0 && errno == EINTR) continue;
            break;
        }
        uint32_t frames = r / sizeof(float), index;
        int32_t filled = spa_ringbuffer_get_write_index(&b->ring, &index);
        if (filled + frames > RING_SIZE) continue; /* nobody is reading; discard */
        spa_ringbuffer_write_data(&b->ring, b->ring_data, RING_SIZE * sizeof(float),
                                  (index % RING_SIZE) * sizeof(float), tmp, frames * sizeof(float));
        spa_ringbuffer_write_update(&b->ring, index + frames);
    }
    fprintf(stderr, "bridge: host output closed\n");
    pw_main_loop_quit(b->loop);
    return NULL;
}

static void on_signal(void *data, int sig) { pw_main_loop_quit(((struct bridge *)data)->loop); }

static pid_t spawn_host(char **argv, int *in_fd, int *out_fd)
{
    int to_host[2], from_host[2];
    if (pipe(to_host) < 0 || pipe(from_host) < 0) return -1;
    pid_t pid = fork();
    if (pid == 0) {
        dup2(to_host[0], 0);
        dup2(from_host[1], 1);
        close(to_host[0]); close(to_host[1]); close(from_host[0]); close(from_host[1]);
        setpgid(0, 0);
        execvp(argv[0], argv);
        perror("bridge: exec host");
        _exit(127);
    }
    close(to_host[0]);
    close(from_host[1]);
    *in_fd = to_host[1];
    *out_fd = from_host[0];
    fcntl(*in_fd, F_SETFL, O_NONBLOCK);
    fcntl(*in_fd, F_SETPIPE_SZ, 16384); /* keep the queue to the host short (~85 ms) */
    return pid;
}

int main(int argc, char **argv)
{
    uint32_t max_latency_ms = 40;
    int i;
    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--max-latency") && i + 1 < argc) max_latency_ms = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--")) { i++; break; }
    }
    if (i >= argc) {
        fprintf(stderr, "usage: %s [--max-latency MS] -- HOST_COMMAND...\n", argv[0]);
        return 2;
    }

    struct bridge *b = &B;
    b->max_latency = max_latency_ms * RATE / 1000;
    spa_ringbuffer_init(&b->ring);
    b->host_pid = spawn_host(argv + i, &b->host_in, &b->host_out);
    if (b->host_pid < 0) return 1;
    signal(SIGPIPE, SIG_IGN);

    pw_init(&argc, &argv);
    b->loop = pw_main_loop_new(NULL);
    pw_loop_add_signal(pw_main_loop_get_loop(b->loop), SIGINT, on_signal, b);
    pw_loop_add_signal(pw_main_loop_get_loop(b->loop), SIGTERM, on_signal, b);
    b->context = pw_context_new(pw_main_loop_get_loop(b->loop), NULL, 0);
    b->core = pw_context_connect(b->context, NULL, 0);
    if (!b->core) { fprintf(stderr, "bridge: cannot connect to PipeWire\n"); return 1; }

    /* The virtual microphone apps record from. Not lingering: it goes away with us. */
    struct pw_properties *mic = pw_properties_new(
        "factory.name", "support.null-audio-sink", PW_KEY_NODE_NAME, "bluevoice_mic",
        PW_KEY_NODE_DESCRIPTION, "Blue VO!CE Microphone", PW_KEY_MEDIA_CLASS, "Audio/Source/Virtual",
        "audio.position", "[ MONO ]", "audio.rate", "48000", PW_KEY_NODE_GROUP, "bluevoice", NULL);
    b->virtual_mic = pw_core_create_object(b->core, "adapter", PW_TYPE_INTERFACE_Node, PW_VERSION_NODE,
                                           &mic->dict, 0);
    pw_properties_free(mic);

    b->filter = pw_filter_new_simple(pw_main_loop_get_loop(b->loop), "bluevoice-dsp",
        pw_properties_new(PW_KEY_MEDIA_TYPE, "Audio", PW_KEY_MEDIA_CATEGORY, "Filter",
                          PW_KEY_MEDIA_ROLE, "DSP", PW_KEY_NODE_NAME, "bluevoice_dsp",
                          PW_KEY_NODE_DESCRIPTION, "Blue VO!CE processing", PW_KEY_APP_NAME, "Blue VO!CE",
                          PW_KEY_NODE_LATENCY, "480/48000", PW_KEY_NODE_AUTOCONNECT, "false",
                          PW_KEY_NODE_GROUP, "bluevoice", NULL),
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

    pthread_create(&b->reader, NULL, reader_main, b);
    fprintf(stderr, "bridge: running (max latency %u ms)\n", max_latency_ms);
    pw_main_loop_run(b->loop);

    fprintf(stderr, "bridge: stopping (dropped in %lu blocks, dropped out %lu frames, underruns %lu)\n",
            b->dropped_in, b->dropped_out, b->underruns);
    close(b->host_in);
    kill(-b->host_pid, SIGTERM);
    waitpid(b->host_pid, NULL, 0);
    pw_filter_destroy(b->filter);
    pw_proxy_destroy(b->virtual_mic);
    pw_core_disconnect(b->core);
    pw_context_destroy(b->context);
    pw_main_loop_destroy(b->loop);
    pw_deinit();
    return 0;
}
