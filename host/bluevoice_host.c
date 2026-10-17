/*
 * bluevoice_host.exe — runs Logitech's Blue VO!CE capture APO
 * (logi_audio_dts_studio_capture_apo.dll) outside the Windows audio engine.
 *
 * Reads mono float32 PCM on stdin, writes processed mono float32 PCM on stdout.
 * Parameters come from a text file of "name value" lines (see params_example.txt);
 * they are served to the APO through its system-effects property store, keyed by
 * PKEY {BA8CAF9F-6B5A-4DDE-830B-29E9EAF6E293} with the pids from the APO's table.
 *
 * Usage: bluevoice_host.exe <apo.dll> <params.txt> [rate] [frames-per-block]
 */
#define COBJMACROS
#define INITGUID
#include <windows.h>
#include <objbase.h>
#include <propsys.h>
#include <mmreg.h>
#include <ks.h>
#include <ksmedia.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <io.h>
#include <math.h>

/* ---- APO interfaces (from the Windows SDK's audioenginebaseapo.h / audiomediatype.h) ---- */

typedef LONGLONG HNSTIME;

typedef struct UNCOMPRESSEDAUDIOFORMAT {
    GUID  guidFormatType;
    DWORD dwSamplesPerFrame;
    DWORD dwBytesPerSampleContainer;
    DWORD dwValidBitsPerSample;
    FLOAT fFramesPerSecond;
    DWORD dwChannelMask;
} UNCOMPRESSEDAUDIOFORMAT;

typedef enum { BUFFER_INVALID = 0, BUFFER_VALID = 1, BUFFER_SILENT = 2 } APO_BUFFER_FLAGS;
typedef enum { APO_CONNECTION_BUFFER_TYPE_ALLOCATED = 0, APO_CONNECTION_BUFFER_TYPE_EXTERNAL = 1,
               APO_CONNECTION_BUFFER_TYPE_DEPENDANT = 2 } APO_CONNECTION_BUFFER_TYPE;

#define APO_CONNECTION_DESCRIPTOR_SIGNATURE 0x41434453 /* 'ACDS' */
#define APO_CONNECTION_PROPERTY_SIGNATURE   0x41435053 /* 'ACPS' */

typedef struct IAudioMediaType IAudioMediaType;

typedef struct APO_CONNECTION_DESCRIPTOR {
    APO_CONNECTION_BUFFER_TYPE Type;
    UINT_PTR         pBuffer;
    UINT32           u32MaxFrameCount;
    IAudioMediaType *pFormat;
    UINT32           u32Signature;
} APO_CONNECTION_DESCRIPTOR;

typedef struct APO_CONNECTION_PROPERTY {
    UINT_PTR         pBuffer;
    UINT32           u32ValidFrameCount;
    APO_BUFFER_FLAGS u32BufferFlags;
    UINT32           u32Signature;
} APO_CONNECTION_PROPERTY;

typedef struct APOInitBaseStruct { UINT32 cbSize; CLSID clsid; } APOInitBaseStruct;

typedef struct APOInitSystemEffects {
    APOInitBaseStruct APOInit;
    IPropertyStore   *pAPOEndpointProperties;
    IPropertyStore   *pAPOSystemEffectsProperties;
    void             *pReserved;
    void             *pDeviceCollection; /* IMMDeviceCollection* */
} APOInitSystemEffects;

typedef struct APOInitSystemEffects2 {
    APOInitBaseStruct APOInit;
    IPropertyStore   *pAPOEndpointProperties;
    IPropertyStore   *pAPOSystemEffectsProperties;
    void             *pReserved;
    void             *pDeviceCollection;
    UINT              nSoftwareIoDeviceInCollection;
    UINT              nSoftwareIoConnectorIndex;
    GUID              AudioProcessingMode;
    BOOL              InitializeForDiscoveryOnly;
} APOInitSystemEffects2;

typedef struct IAudioMediaTypeVtbl {
    HRESULT (STDMETHODCALLTYPE *QueryInterface)(IAudioMediaType *, REFIID, void **);
    ULONG   (STDMETHODCALLTYPE *AddRef)(IAudioMediaType *);
    ULONG   (STDMETHODCALLTYPE *Release)(IAudioMediaType *);
    HRESULT (STDMETHODCALLTYPE *IsCompressedFormat)(IAudioMediaType *, BOOL *);
    HRESULT (STDMETHODCALLTYPE *IsEqual)(IAudioMediaType *, IAudioMediaType *, DWORD *);
    const WAVEFORMATEX *(STDMETHODCALLTYPE *GetAudioFormat)(IAudioMediaType *);
    HRESULT (STDMETHODCALLTYPE *GetUncompressedAudioFormat)(IAudioMediaType *, UNCOMPRESSEDAUDIOFORMAT *);
} IAudioMediaTypeVtbl;
struct IAudioMediaType { const IAudioMediaTypeVtbl *lpVtbl; };

typedef struct IAudioProcessingObject IAudioProcessingObject;
typedef struct IAudioProcessingObjectVtbl {
    HRESULT (STDMETHODCALLTYPE *QueryInterface)(IAudioProcessingObject *, REFIID, void **);
    ULONG   (STDMETHODCALLTYPE *AddRef)(IAudioProcessingObject *);
    ULONG   (STDMETHODCALLTYPE *Release)(IAudioProcessingObject *);
    HRESULT (STDMETHODCALLTYPE *Reset)(IAudioProcessingObject *);
    HRESULT (STDMETHODCALLTYPE *GetLatency)(IAudioProcessingObject *, HNSTIME *);
    HRESULT (STDMETHODCALLTYPE *GetRegistrationProperties)(IAudioProcessingObject *, void **);
    HRESULT (STDMETHODCALLTYPE *Initialize)(IAudioProcessingObject *, UINT32, BYTE *);
    HRESULT (STDMETHODCALLTYPE *IsInputFormatSupported)(IAudioProcessingObject *, IAudioMediaType *, IAudioMediaType *, IAudioMediaType **);
    HRESULT (STDMETHODCALLTYPE *IsOutputFormatSupported)(IAudioProcessingObject *, IAudioMediaType *, IAudioMediaType *, IAudioMediaType **);
    HRESULT (STDMETHODCALLTYPE *GetInputChannelCount)(IAudioProcessingObject *, UINT32 *);
} IAudioProcessingObjectVtbl;
struct IAudioProcessingObject { const IAudioProcessingObjectVtbl *lpVtbl; };

typedef struct IAudioProcessingObjectRT IAudioProcessingObjectRT;
typedef struct IAudioProcessingObjectRTVtbl {
    HRESULT (STDMETHODCALLTYPE *QueryInterface)(IAudioProcessingObjectRT *, REFIID, void **);
    ULONG   (STDMETHODCALLTYPE *AddRef)(IAudioProcessingObjectRT *);
    ULONG   (STDMETHODCALLTYPE *Release)(IAudioProcessingObjectRT *);
    void    (STDMETHODCALLTYPE *APOProcess)(IAudioProcessingObjectRT *, UINT32, APO_CONNECTION_PROPERTY **, UINT32, APO_CONNECTION_PROPERTY **);
    UINT32  (STDMETHODCALLTYPE *CalcInputFrames)(IAudioProcessingObjectRT *, UINT32);
    UINT32  (STDMETHODCALLTYPE *CalcOutputFrames)(IAudioProcessingObjectRT *, UINT32);
} IAudioProcessingObjectRTVtbl;
struct IAudioProcessingObjectRT { const IAudioProcessingObjectRTVtbl *lpVtbl; };

typedef struct IAudioProcessingObjectConfiguration IAudioProcessingObjectConfiguration;
typedef struct IAudioProcessingObjectConfigurationVtbl {
    HRESULT (STDMETHODCALLTYPE *QueryInterface)(IAudioProcessingObjectConfiguration *, REFIID, void **);
    ULONG   (STDMETHODCALLTYPE *AddRef)(IAudioProcessingObjectConfiguration *);
    ULONG   (STDMETHODCALLTYPE *Release)(IAudioProcessingObjectConfiguration *);
    HRESULT (STDMETHODCALLTYPE *LockForProcess)(IAudioProcessingObjectConfiguration *, UINT32, APO_CONNECTION_DESCRIPTOR **, UINT32, APO_CONNECTION_DESCRIPTOR **);
    HRESULT (STDMETHODCALLTYPE *UnlockForProcess)(IAudioProcessingObjectConfiguration *);
} IAudioProcessingObjectConfigurationVtbl;
struct IAudioProcessingObjectConfiguration { const IAudioProcessingObjectConfigurationVtbl *lpVtbl; };

DEFINE_GUID(IID_IAudioProcessingObject,              0xFD7F2B29, 0x24D0, 0x4B5C, 0xB1, 0x77, 0x59, 0x2C, 0x39, 0xF9, 0xCA, 0x10);
DEFINE_GUID(IID_IAudioProcessingObjectRT,            0x9E1D6A6D, 0xDDBC, 0x4E95, 0xA4, 0xC7, 0xAD, 0x64, 0xBA, 0x37, 0x84, 0x6C);
DEFINE_GUID(IID_IAudioProcessingObjectConfiguration, 0x0E5ED805, 0xABA6, 0x49C3, 0x8F, 0x9A, 0x2B, 0x8C, 0x88, 0x9C, 0x4F, 0xA8);
DEFINE_GUID(IID_IAudioMediaType,                     0x4E997F73, 0xB71F, 0x4798, 0x87, 0x3B, 0xED, 0x7D, 0xFC, 0xF1, 0x5B, 0x4D);
DEFINE_GUID(CLSID_DTSStudioAPOGFX,                   0x4BD94DA9, 0xBE3B, 0x4523, 0x90, 0x72, 0x6E, 0xAD, 0x0A, 0xF5, 0x50, 0x5E);
DEFINE_GUID(FMTID_BlueVoice,                         0xBA8CAF9F, 0x6B5A, 0x4DDE, 0x83, 0x0B, 0x29, 0xE9, 0xEA, 0xF6, 0xE2, 0x93);
DEFINE_GUID(KSDATAFORMAT_SUBTYPE_IEEE_FLOAT_,        0x00000003, 0x0000, 0x0010, 0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71);

static FILE *log_out;
static int verbose;
#define LOG(...) do { fprintf(log_out, __VA_ARGS__); fflush(log_out); } while (0)

static void guid_str(const GUID *g, char *out)
{
    sprintf(out, "{%08lX-%04X-%04X-%02X%02X-%02X%02X%02X%02X%02X%02X}", (unsigned long)g->Data1, g->Data2, g->Data3,
            g->Data4[0], g->Data4[1], g->Data4[2], g->Data4[3], g->Data4[4], g->Data4[5], g->Data4[6], g->Data4[7]);
}

/* ---- parameter table: pid, name, VARTYPE (from FUN_1800016c0 in the APO) ---- */

typedef struct { DWORD pid; const char *name; VARTYPE vt; float value; int set; } Param;

static Param params[] = {
    {2, "micopt.meter_enable", VT_I4}, {100, "micopt.enable", VT_I4}, {101, "micopt.balance", VT_R4},
    {102, "micopt.volume", VT_R4},
    {200, "dpop.enable", VT_I4}, {201, "dpop.freq", VT_R4},
    {300, "nr.enable", VT_I4}, {301, "nr.release", VT_R4}, {302, "nr.sensitivity", VT_R4},
    {303, "nr.bias", VT_R4}, {304, "nr.attenuation_max", VT_R4},
    {400, "exp.enable", VT_I4}, {401, "exp.attack", VT_R4}, {402, "exp.release", VT_R4},
    {403, "exp.hysteresis", VT_R4}, {404, "exp.ratio", VT_R4}, {405, "exp.thresh", VT_R4},
    {406, "exp.thresh_auto_enable", VT_I4}, {407, "exp.thresh_auto_sense", VT_R4},
    {408, "exp.attenuation_max", VT_R4},
    {500, "veq.enable", VT_I4}, {501, "veq.low_gain", VT_R4}, {502, "veq.low_freq", VT_R4},
    {503, "veq.low_width", VT_R4}, {504, "veq.mid_gain", VT_R4}, {505, "veq.mid_freq", VT_R4},
    {506, "veq.mid_width", VT_R4}, {507, "veq.high_gain", VT_R4}, {508, "veq.high_freq", VT_R4},
    {509, "veq.high_width", VT_R4},
    {600, "des.enable", VT_I4}, {601, "des.attack", VT_R4}, {602, "des.release", VT_R4},
    {603, "des.ratio", VT_R4}, {604, "des.thresh", VT_R4}, {605, "des.freq", VT_R4},
    {700, "comp.enable", VT_I4}, {701, "comp.attack", VT_R4}, {702, "comp.release", VT_R4},
    {703, "comp.ratio", VT_R4}, {704, "comp.thresh", VT_R4}, {705, "comp.makeup", VT_R4},
    {800, "lim.boost", VT_R4}, {801, "lim.attack", VT_R4}, {802, "lim.release", VT_R4},
};
#define NPARAMS (sizeof(params) / sizeof(params[0]))

static Param *param_by_name(const char *n)
{
    for (size_t i = 0; i < NPARAMS; i++) if (!strcmp(params[i].name, n)) return &params[i];
    return NULL;
}

static int load_params(const char *path)
{
    FILE *f = fopen(path, "r");
    char line[256], name[128];
    float v;
    if (!f) { LOG("cannot open params file %s\n", path); return 0; }
    for (size_t i = 0; i < NPARAMS; i++) params[i].set = 0;
    while (fgets(line, sizeof line, f)) {
        if (line[0] == '#' || sscanf(line, "%127s %f", name, &v) != 2) continue;
        Param *p = param_by_name(name);
        if (!p) { LOG("unknown parameter %s\n", name); continue; }
        p->value = v;
        p->set = 1;
    }
    fclose(f);
    return 1;
}

/* ---- IPropertyStore that serves the parameters and logs every lookup ---- */

typedef struct { IPropertyStore iface; LONG ref; const char *label; } Store;

static HRESULT STDMETHODCALLTYPE ps_QueryInterface(IPropertyStore *This, REFIID riid, void **ppv)
{
    if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IPropertyStore)) {
        *ppv = This;
        IPropertyStore_AddRef(This);
        return S_OK;
    }
    char g[64];
    guid_str(riid, g);
    LOG("store QI for unsupported %s\n", g);
    *ppv = NULL;
    return E_NOINTERFACE;
}
static ULONG STDMETHODCALLTYPE ps_AddRef(IPropertyStore *This) { return InterlockedIncrement(&((Store *)This)->ref); }
static ULONG STDMETHODCALLTYPE ps_Release(IPropertyStore *This) { return InterlockedDecrement(&((Store *)This)->ref); }
static HRESULT STDMETHODCALLTYPE ps_GetCount(IPropertyStore *This, DWORD *c) { *c = 0; return S_OK; }
static HRESULT STDMETHODCALLTYPE ps_GetAt(IPropertyStore *This, DWORD i, PROPERTYKEY *k) { return E_INVALIDARG; }
static HRESULT STDMETHODCALLTYPE ps_SetValue(IPropertyStore *This, REFPROPERTYKEY k, REFPROPVARIANT v) { return S_OK; }
static HRESULT STDMETHODCALLTYPE ps_Commit(IPropertyStore *This) { return S_OK; }

static HRESULT STDMETHODCALLTYPE ps_GetValue(IPropertyStore *This, REFPROPERTYKEY key, PROPVARIANT *pv)
{
    Store *s = (Store *)This;
    char g[64];
    PropVariantInit(pv);
    if (IsEqualGUID(&key->fmtid, &FMTID_BlueVoice)) {
        for (size_t i = 0; i < NPARAMS; i++) {
            if (params[i].pid != key->pid) continue;
            if (!params[i].set) { if (verbose) LOG("[%s] get %s -> (unset)\n", s->label, params[i].name); return S_OK; }
            pv->vt = params[i].vt;
            if (params[i].vt == VT_I4) pv->lVal = (LONG)params[i].value;
            else pv->fltVal = params[i].value;
            if (verbose) LOG("[%s] get %s -> %g\n", s->label, params[i].name, params[i].value);
            return S_OK;
        }
    }
    guid_str(&key->fmtid, g);
    if (verbose) LOG("[%s] get %s,%lu -> (empty)\n", s->label, g, (unsigned long)key->pid);
    return S_OK;
}

static const IPropertyStoreVtbl ps_vtbl = {
    ps_QueryInterface, ps_AddRef, ps_Release, ps_GetCount, ps_GetAt, ps_GetValue, ps_SetValue, ps_Commit,
};

/* ---- empty IMMDeviceCollection: CAPObase::Initialize rejects a null collection ---- */

typedef struct EmptyCollection EmptyCollection;
typedef struct {
    HRESULT (STDMETHODCALLTYPE *QueryInterface)(EmptyCollection *, REFIID, void **);
    ULONG   (STDMETHODCALLTYPE *AddRef)(EmptyCollection *);
    ULONG   (STDMETHODCALLTYPE *Release)(EmptyCollection *);
    HRESULT (STDMETHODCALLTYPE *GetCount)(EmptyCollection *, UINT *);
    HRESULT (STDMETHODCALLTYPE *Item)(EmptyCollection *, UINT, void **);
} EmptyCollectionVtbl;
struct EmptyCollection { const EmptyCollectionVtbl *lpVtbl; };

static HRESULT STDMETHODCALLTYPE dc_QueryInterface(EmptyCollection *This, REFIID riid, void **ppv)
{
    *ppv = This;
    return S_OK;
}
static ULONG STDMETHODCALLTYPE dc_AddRef(EmptyCollection *This) { return 1; }
static ULONG STDMETHODCALLTYPE dc_Release(EmptyCollection *This) { return 1; }
static HRESULT STDMETHODCALLTYPE dc_GetCount(EmptyCollection *This, UINT *n) { *n = 0; return S_OK; }
static HRESULT STDMETHODCALLTYPE dc_Item(EmptyCollection *This, UINT i, void **dev) { *dev = NULL; return E_INVALIDARG; }

static const EmptyCollectionVtbl dc_vtbl = { dc_QueryInterface, dc_AddRef, dc_Release, dc_GetCount, dc_Item };
static EmptyCollection empty_collection = { &dc_vtbl };

/* ---- IAudioMediaType for mono float32 ---- */

typedef struct { IAudioMediaType iface; LONG ref; WAVEFORMATEXTENSIBLE wfx; } MediaType;

static HRESULT STDMETHODCALLTYPE mt_QueryInterface(IAudioMediaType *This, REFIID riid, void **ppv)
{
    if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IAudioMediaType)) {
        *ppv = This;
        This->lpVtbl->AddRef(This);
        return S_OK;
    }
    *ppv = NULL;
    return E_NOINTERFACE;
}
static ULONG STDMETHODCALLTYPE mt_AddRef(IAudioMediaType *This) { return InterlockedIncrement(&((MediaType *)This)->ref); }
static ULONG STDMETHODCALLTYPE mt_Release(IAudioMediaType *This) { return InterlockedDecrement(&((MediaType *)This)->ref); }
static HRESULT STDMETHODCALLTYPE mt_IsCompressedFormat(IAudioMediaType *This, BOOL *c) { *c = FALSE; return S_OK; }
static HRESULT STDMETHODCALLTYPE mt_IsEqual(IAudioMediaType *This, IAudioMediaType *o, DWORD *flags)
{
    *flags = 0x0f; /* AUDIOMEDIATYPE_EQUAL_FORMAT_TYPES | _DATA | _USER_DATA, as Windows reports for identical types */
    return S_OK;
}
static const WAVEFORMATEX *STDMETHODCALLTYPE mt_GetAudioFormat(IAudioMediaType *This) { return &((MediaType *)This)->wfx.Format; }
static HRESULT STDMETHODCALLTYPE mt_GetUncompressedAudioFormat(IAudioMediaType *This, UNCOMPRESSEDAUDIOFORMAT *u)
{
    MediaType *m = (MediaType *)This;
    u->guidFormatType = KSDATAFORMAT_SUBTYPE_IEEE_FLOAT_;
    u->dwSamplesPerFrame = m->wfx.Format.nChannels;
    u->dwBytesPerSampleContainer = 4;
    u->dwValidBitsPerSample = 32;
    u->fFramesPerSecond = (FLOAT)m->wfx.Format.nSamplesPerSec;
    u->dwChannelMask = m->wfx.dwChannelMask;
    return S_OK;
}

static const IAudioMediaTypeVtbl mt_vtbl = {
    mt_QueryInterface, mt_AddRef, mt_Release, mt_IsCompressedFormat, mt_IsEqual, mt_GetAudioFormat,
    mt_GetUncompressedAudioFormat,
};

static void media_type_init(MediaType *m, DWORD rate, WORD channels)
{
    memset(m, 0, sizeof *m);
    m->iface.lpVtbl = &mt_vtbl;
    m->ref = 1;
    m->wfx.Format.wFormatTag = WAVE_FORMAT_EXTENSIBLE;
    m->wfx.Format.nChannels = channels;
    m->wfx.Format.nSamplesPerSec = rate;
    m->wfx.Format.wBitsPerSample = 32;
    m->wfx.Format.nBlockAlign = 4 * channels;
    m->wfx.Format.nAvgBytesPerSec = rate * 4 * channels;
    m->wfx.Format.cbSize = sizeof(WAVEFORMATEXTENSIBLE) - sizeof(WAVEFORMATEX);
    m->wfx.Samples.wValidBitsPerSample = 32;
    m->wfx.dwChannelMask = channels == 1 ? SPEAKER_FRONT_CENTER : (SPEAKER_FRONT_LEFT | SPEAKER_FRONT_RIGHT);
    m->wfx.SubFormat = KSDATAFORMAT_SUBTYPE_IEEE_FLOAT_;
}

/* ---- engine: one APO instance, locked for processing ---- */

typedef HRESULT (WINAPI *DllGetClassObject_t)(REFCLSID, REFIID, void **);

typedef struct {
    IAudioProcessingObject *apo;
    IAudioProcessingObjectConfiguration *cfg;
    IAudioProcessingObjectRT *rt;
    float *in, *out;                 /* each instance owns its connection buffers */
    APO_CONNECTION_PROPERTY in_prop, out_prop;
} Engine;

static IClassFactory *factory;
static Store fx_store = {{(IPropertyStoreVtbl *)&ps_vtbl}, 1, "fx"};
static Store ep_store = {{(IPropertyStoreVtbl *)&ps_vtbl}, 1, "endpoint"};
static MediaType in_fmt, out_fmt;
static UINT32 block;

static void engine_release(Engine *e)
{
    if (e->cfg) { e->cfg->lpVtbl->UnlockForProcess(e->cfg); e->cfg->lpVtbl->Release(e->cfg); }
    if (e->rt) e->rt->lpVtbl->Release(e->rt);
    if (e->apo) e->apo->lpVtbl->Release(e->apo);
    if (e->in) _aligned_free(e->in);
    if (e->out) _aligned_free(e->out);
    memset(e, 0, sizeof *e);
}

static int engine_create(Engine *e)
{
    HRESULT hr;
    memset(e, 0, sizeof *e);
    e->in = _aligned_malloc(block * sizeof(float), 64);
    e->out = _aligned_malloc(block * sizeof(float), 64);
    APO_CONNECTION_PROPERTY ip = {(UINT_PTR)e->in, block, BUFFER_VALID, APO_CONNECTION_PROPERTY_SIGNATURE};
    APO_CONNECTION_PROPERTY op = {(UINT_PTR)e->out, block, BUFFER_VALID, APO_CONNECTION_PROPERTY_SIGNATURE};
    e->in_prop = ip;
    e->out_prop = op;
    hr = IClassFactory_CreateInstance(factory, NULL, &IID_IAudioProcessingObject, (void **)&e->apo);
    if (FAILED(hr)) { LOG("CreateInstance: 0x%08lx\n", hr); return 0; }

    APOInitSystemEffects2 init = {0};
    init.APOInit.cbSize = sizeof init;
    init.APOInit.clsid = CLSID_DTSStudioAPOGFX;
    init.pAPOEndpointProperties = &ep_store.iface;
    init.pAPOSystemEffectsProperties = &fx_store.iface;
    init.pDeviceCollection = &empty_collection;
    hr = e->apo->lpVtbl->Initialize(e->apo, sizeof init, (BYTE *)&init);
    if (FAILED(hr)) { LOG("Initialize: 0x%08lx\n", hr); engine_release(e); return 0; }

    IAudioMediaType *supported = NULL;
    hr = e->apo->lpVtbl->IsInputFormatSupported(e->apo, &out_fmt.iface, &in_fmt.iface, &supported);
    if (FAILED(hr)) LOG("IsInputFormatSupported: 0x%08lx\n", hr);

    e->apo->lpVtbl->QueryInterface(e->apo, &IID_IAudioProcessingObjectConfiguration, (void **)&e->cfg);
    e->apo->lpVtbl->QueryInterface(e->apo, &IID_IAudioProcessingObjectRT, (void **)&e->rt);
    if (!e->cfg || !e->rt) { LOG("APO lacks configuration/RT interfaces\n"); engine_release(e); return 0; }

    APO_CONNECTION_DESCRIPTOR in_desc = {APO_CONNECTION_BUFFER_TYPE_EXTERNAL, (UINT_PTR)e->in, block, &in_fmt.iface,
                                         APO_CONNECTION_DESCRIPTOR_SIGNATURE};
    APO_CONNECTION_DESCRIPTOR out_desc = {APO_CONNECTION_BUFFER_TYPE_EXTERNAL, (UINT_PTR)e->out, block, &out_fmt.iface,
                                          APO_CONNECTION_DESCRIPTOR_SIGNATURE};
    APO_CONNECTION_DESCRIPTOR *ins[] = {&in_desc}, *outs[] = {&out_desc};
    hr = e->cfg->lpVtbl->LockForProcess(e->cfg, 1, ins, 1, outs);
    if (FAILED(hr)) { LOG("LockForProcess: 0x%08lx\n", hr); engine_release(e); return 0; }
    return 1;
}

static FILETIME params_mtime(const char *path)
{
    WIN32_FILE_ATTRIBUTE_DATA a;
    FILETIME zero = {0};
    return GetFileAttributesExA(path, GetFileExInfoStandard, &a) ? a.ftLastWriteTime : zero;
}

static size_t read_full(void *buf, size_t n)
{
    size_t got = 0;
    while (got < n) {
        size_t r = fread((char *)buf + got, 1, n - got, stdin);
        if (r == 0) break;
        got += r;
    }
    return got;
}

/* Run one block through an instance; the result is left in e->out. */
static void engine_process(Engine *e, const float *input)
{
    APO_CONNECTION_PROPERTY *inp[] = {&e->in_prop}, *outp[] = {&e->out_prop};
    memcpy(e->in, input, block * sizeof(float));
    e->in_prop.u32ValidFrameCount = block;
    e->in_prop.u32BufferFlags = BUFFER_VALID;
    e->out_prop.u32BufferFlags = BUFFER_VALID;
    e->rt->lpVtbl->APOProcess(e->rt, 1, inp, 1, outp);
    if (e->out_prop.u32BufferFlags == BUFFER_SILENT) memset(e->out, 0, block * sizeof(float));
}

static double rms_db(const float *x, UINT32 n)
{
    double acc = 0;
    for (UINT32 i = 0; i < n; i++) acc += (double)x[i] * x[i];
    return acc > 0 ? 10.0 * log10(acc / n) : -120.0;
}

/* ---- main ---- */

int main(int argc, char **argv)
{
    log_out = stderr;
    if (argc < 3) {
        LOG("usage: %s <apo.dll> <params.txt> [rate] [frames-per-block]\n"
            "  stdin/stdout: mono float32 PCM. The params file is re-read whenever it changes.\n"
            "  stderr: 'meter <in dBFS> <out dBFS>' every 100 ms; set BLUEVOICE_DEBUG=1 for property traces.\n", argv[0]);
        return 2;
    }
    DWORD rate = argc > 3 ? (DWORD)atoi(argv[3]) : 48000;
    block = argc > 4 ? (UINT32)atoi(argv[4]) : rate / 100;
    verbose = getenv("BLUEVOICE_DEBUG") != NULL;
    const char *params_path = argv[2];

    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
    if (!load_params(params_path)) return 1;
    FILETIME mtime = params_mtime(params_path);

    CoInitializeEx(NULL, COINIT_MULTITHREADED);
    HMODULE dll = LoadLibraryA(argv[1]);
    if (!dll) { LOG("LoadLibrary failed: %lu\n", GetLastError()); return 1; }
    DllGetClassObject_t get_class = (DllGetClassObject_t)GetProcAddress(dll, "DllGetClassObject");
    HRESULT hr = get_class ? get_class(&CLSID_DTSStudioAPOGFX, &IID_IClassFactory, (void **)&factory) : E_FAIL;
    if (FAILED(hr)) { LOG("DllGetClassObject: 0x%08lx\n", hr); return 1; }

    media_type_init(&in_fmt, rate, 1);
    media_type_init(&out_fmt, rate, 1);
    float *input = _aligned_malloc(block * sizeof(float), 64);
    float *output = _aligned_malloc(block * sizeof(float), 64);

    Engine engine, next = {0};
    if (!engine_create(&engine)) return 1;
    LOG("ready rate=%lu block=%u\n", (unsigned long)rate, block);

    /* A new instance starts with empty filter and detector state, so switching abruptly clicks.
     * It first runs alongside the old one for WARMUP blocks (output discarded), then the two
     * are crossfaded over XFADE blocks. */
    const UINT32 WARMUP = rate / 10 / block ? rate / 10 / block : 1;   /* ~100 ms */
    const UINT32 XFADE = rate * 3 / 100 / block ? rate * 3 / 100 / block : 1; /* ~30 ms */
    UINT32 next_age = 0;
    size_t bytes = block * sizeof(float);
    UINT32 meter_every = rate / 10 / block ? rate / 10 / block : 1;
    double in_db = -120.0, out_db = -120.0;
    unsigned long blocks = 0;

    for (;;) {
        size_t got = read_full(input, bytes);
        if (got == 0) break;
        if (got < bytes) memset((char *)input + got, 0, bytes - got);

        if (blocks % meter_every == 0 && !next.apo) {
            FILETIME now = params_mtime(params_path);
            if (CompareFileTime(&now, &mtime) != 0) {
                mtime = now;
                if (load_params(params_path) && engine_create(&next)) next_age = 0;
            }
        }

        engine_process(&engine, input);
        memcpy(output, engine.out, bytes);
        if (next.apo) {
            engine_process(&next, input);
            if (next_age >= WARMUP) {
                UINT32 k = next_age - WARMUP;
                for (UINT32 i = 0; i < block; i++) {
                    float g = (float)(k * block + i) / (float)(XFADE * block);
                    output[i] = (1.0f - g) * engine.out[i] + g * next.out[i];
                }
                if (k + 1 >= XFADE) {
                    engine_release(&engine);
                    engine = next;
                    memset(&next, 0, sizeof next);
                    LOG("reloaded parameters\n");
                }
            }
            next_age++;
        }
        fwrite(output, 1, got, stdout);
        fflush(stdout);

        double level_in = rms_db(input, block), level_out = rms_db(output, block);
        in_db = in_db > level_in ? in_db : level_in;
        out_db = out_db > level_out ? out_db : level_out;
        if (++blocks % meter_every == 0) {
            LOG("meter %.1f %.1f\n", in_db, out_db);
            in_db = out_db = -120.0;
        }
    }
    if (next.apo) engine_release(&next);
    engine_release(&engine);
    return 0;
}
