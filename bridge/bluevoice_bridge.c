/*
 * bluevoice-bridge — connects a real microphone to Logitech's Blue VO!CE APO (running in
 * bluevoice_host.exe under Wine) and publishes the result as a virtual PipeWire microphone.
 *
 *   mic --capture stream--> host stdin --APO--> host stdout --ring--> "Blue VO!CE Microphone"
 *
 * The capture stream only runs while some application records from the virtual microphone.
 * Latency through the ring is capped: anything beyond --max-latency is dropped.
 *
 * Usage: bluevoice-bridge [--target MIC_NODE] [--max-latency MS] -- wine bluevoice_host.exe APO PARAMS
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
#include <spa/param/audio/format-utils.h>
#include <spa/utils/ringbuffer.h>

#define RATE 48000
#define RING_SIZE (1u << 16) /* floats; must be a power of two (~1.4 s) */

struct bridge {
    struct pw_main_loop *loop;
    struct pw_stream *capture;
    struct pw_stream *source;
    struct spa_hook capture_listener, source_listener;

    int host_in, host_out; /* our ends of the host's stdin / stdout */
    pid_t host_pid;
    pthread_t reader;

    struct spa_ringbuffer ring;
    float ring_data[RING_SIZE];
    uint32_t max_latency; /* frames */
    unsigned long dropped_in, dropped_out, underruns;
};

static struct bridge B;

/* Mic -> host. Runs in the realtime thread, so the pipe write must never block. */
static void on_capture_process(void *data)
{
    struct bridge *b = data;
    struct pw_buffer *buf = pw_stream_dequeue_buffer(b->capture);
    if (!buf) return;
    struct spa_data *d = &buf->buffer->datas[0];
    if (d->data && d->chunk->size) {
        ssize_t w = write(b->host_in, SPA_PTROFF(d->data, d->chunk->offset, void), d->chunk->size);
        if (w < (ssize_t)d->chunk->size) b->dropped_in++;
    }
    pw_stream_queue_buffer(b->capture, buf);
}

/* Ring -> virtual microphone. */
static void on_source_process(void *data)
{
    struct bridge *b = data;
    struct pw_buffer *buf = pw_stream_dequeue_buffer(b->source);
    if (!buf) return;
    struct spa_data *d = &buf->buffer->datas[0];
    float *dst = d->data;
    if (!dst) { pw_stream_queue_buffer(b->source, buf); return; }

    uint32_t frames = d->maxsize / sizeof(float);
    if (buf->requested && buf->requested < frames) frames = buf->requested;

    uint32_t index;
    int32_t avail = spa_ringbuffer_get_read_index(&b->ring, &index);
    if (avail > (int32_t)(b->max_latency + frames)) {
        /* Too much buffered: skip ahead so delay stays bounded. */
        uint32_t skip = avail - b->max_latency;
        index += skip;
        avail -= skip;
        spa_ringbuffer_read_update(&b->ring, index);
        b->dropped_out += skip;
    }
    uint32_t n = avail < (int32_t)frames ? (avail > 0 ? (uint32_t)avail : 0) : frames;
    spa_ringbuffer_read_data(&b->ring, b->ring_data, RING_SIZE * sizeof(float),
                             (index % RING_SIZE) * sizeof(float), dst, n * sizeof(float));
    spa_ringbuffer_read_update(&b->ring, index + n);
    if (n < frames) {
        memset(dst + n, 0, (frames - n) * sizeof(float));
        b->underruns++;
    }

    d->chunk->offset = 0;
    d->chunk->stride = sizeof(float);
    d->chunk->size = frames * sizeof(float);
    pw_stream_queue_buffer(b->source, buf);
}

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

/* Run the mic only while something consumes the virtual microphone. */
static void on_source_state(void *data, enum pw_stream_state old, enum pw_stream_state state, const char *error)
{
    struct bridge *b = data;
    bool active = state == PW_STREAM_STATE_STREAMING;
    fprintf(stderr, "bridge: virtual mic %s\n", pw_stream_state_as_string(state));
    pw_stream_set_active(b->capture, active);
    if (!active) {
        /* Forget stale audio so the next listener starts fresh. */
        uint32_t index;
        spa_ringbuffer_get_write_index(&b->ring, &index);
        spa_ringbuffer_read_update(&b->ring, index);
    }
}

static void on_capture_state(void *data, enum pw_stream_state old, enum pw_stream_state state, const char *error)
{
    if (state == PW_STREAM_STATE_ERROR) fprintf(stderr, "bridge: capture error: %s\n", error ? error : "?");
}

static const struct pw_stream_events capture_events = {
    PW_VERSION_STREAM_EVENTS, .state_changed = on_capture_state, .process = on_capture_process,
};
static const struct pw_stream_events source_events = {
    PW_VERSION_STREAM_EVENTS, .state_changed = on_source_state, .process = on_source_process,
};

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

static const struct spa_pod *mono_f32_format(struct spa_pod_builder *pb)
{
    struct spa_audio_info_raw info = {
        .format = SPA_AUDIO_FORMAT_F32, .rate = RATE, .channels = 1, .position = {SPA_AUDIO_CHANNEL_MONO},
    };
    return spa_format_audio_raw_build(pb, SPA_PARAM_EnumFormat, &info);
}

int main(int argc, char **argv)
{
    const char *target = NULL;
    uint32_t max_latency_ms = 40;
    int i;
    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--target") && i + 1 < argc) target = argv[++i];
        else if (!strcmp(argv[i], "--max-latency") && i + 1 < argc) max_latency_ms = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--")) { i++; break; }
    }
    if (i >= argc) {
        fprintf(stderr, "usage: %s [--target MIC_NODE] [--max-latency MS] -- HOST_COMMAND...\n", argv[0]);
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

    struct pw_properties *cprops = pw_properties_new(
        PW_KEY_MEDIA_TYPE, "Audio", PW_KEY_MEDIA_CATEGORY, "Capture", PW_KEY_MEDIA_ROLE, "Communication",
        PW_KEY_NODE_NAME, "bluevoice_capture", PW_KEY_NODE_DESCRIPTION, "Blue VO!CE input",
        PW_KEY_APP_NAME, "Blue VO!CE", PW_KEY_NODE_LATENCY, "480/48000",
        PW_KEY_NODE_DONT_RECONNECT, target ? "true" : "false", NULL);
    if (target) pw_properties_set(cprops, PW_KEY_TARGET_OBJECT, target);
    b->capture = pw_stream_new_simple(pw_main_loop_get_loop(b->loop), "bluevoice-capture", cprops, &capture_events, b);

    struct pw_properties *sprops = pw_properties_new(
        PW_KEY_MEDIA_TYPE, "Audio", PW_KEY_MEDIA_CLASS, "Audio/Source/Virtual",
        PW_KEY_NODE_NAME, "bluevoice_mic", PW_KEY_NODE_DESCRIPTION, "Blue VO!CE Microphone",
        PW_KEY_APP_NAME, "Blue VO!CE", PW_KEY_NODE_LATENCY, "480/48000", "audio.position", "[ MONO ]", NULL);
    b->source = pw_stream_new_simple(pw_main_loop_get_loop(b->loop), "bluevoice-mic", sprops, &source_events, b);

    uint8_t buffer[1024];
    struct spa_pod_builder pb = SPA_POD_BUILDER_INIT(buffer, sizeof buffer);
    const struct spa_pod *params[1];

    params[0] = mono_f32_format(&pb);
    pw_stream_connect(b->capture, PW_DIRECTION_INPUT, PW_ID_ANY,
                      PW_STREAM_FLAG_AUTOCONNECT | PW_STREAM_FLAG_MAP_BUFFERS | PW_STREAM_FLAG_RT_PROCESS |
                      PW_STREAM_FLAG_INACTIVE, params, 1);
    params[0] = mono_f32_format(&pb);
    pw_stream_connect(b->source, PW_DIRECTION_OUTPUT, PW_ID_ANY,
                      PW_STREAM_FLAG_MAP_BUFFERS | PW_STREAM_FLAG_RT_PROCESS, params, 1);

    pthread_create(&b->reader, NULL, reader_main, b);
    fprintf(stderr, "bridge: running (target %s, max latency %u ms)\n", target ? target : "default", max_latency_ms);
    pw_main_loop_run(b->loop);

    fprintf(stderr, "bridge: stopping (dropped in %lu, dropped out %lu frames, underruns %lu)\n",
            b->dropped_in, b->dropped_out, b->underruns);
    close(b->host_in);
    kill(-b->host_pid, SIGTERM);
    waitpid(b->host_pid, NULL, 0);
    pw_stream_destroy(b->capture);
    pw_stream_destroy(b->source);
    pw_main_loop_destroy(b->loop);
    pw_deinit();
    return 0;
}
