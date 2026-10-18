#!/usr/bin/env python3
"""Compare the native MicOpt loader against Logitech's APO under Wine, one stage at a time.

Both process test/speech_noisy.f32 with the same parameters; the APO adds 256 samples of its own
buffering, so its output is compared 256 samples later. Run from host/.
"""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, '..')
import presets  # noqa: E402

DLL = '../re/apo_dlls/logi_audio_dts_studio_capture_apo.dll'
WINE_DLL = 'Z:' + os.path.abspath(DLL).replace('/', '\\')
ENV = dict(os.environ, WINEPREFIX=os.path.expanduser('~/lghub/wine'), WINEDEBUG='-all',
		   WINEDLLOVERRIDES='winepulse.drv,winealsa.drv,wineoss.drv=d')
SRC = 'test/speech_noisy.f32'
PARAMS_EXT = '.params'
APO_EXTRA = 256

BC1 = next(p for _, n, p in presets.load_ghub_presets('../re/presets/pro_x_headset_device_presets.json')
           if n == 'Broadcaster 1')


def stage(**on):
	p = dict(BC1)
	for key in ('dpop.enable', 'nr.enable', 'exp.enable', 'veq.enable', 'des.enable', 'comp.enable'):
		p[key] = 1 if key.split('.')[0] in on else 0
	if 'lim' not in on:
		p['lim.boost'] = 1.0
	if 'vol' not in on:
		p['micopt.volume'] = 1.0
	return p


CASES = {
	'volume only': stage(vol=1),
	'limiter boost': stage(lim=1),
	'high-pass': stage(dpop=1),
	'voice EQ': stage(veq=1),
	'noise reduction': stage(nr=1),
	'gate': stage(exp=1),
	'de-esser': stage(des=1),
	'compressor': stage(comp=1),
	'full Broadcaster 1': BC1,
}


def run(name, params):
	path = f'test/cmp_{name.replace(" ", "_")}'
	with open(path + PARAMS_EXT, 'w') as f:
		f.write(presets.params_text(params))
	subprocess.run(['../bridge/micopt_test', DLL, path + PARAMS_EXT, SRC, path + '.native.f32'],
				   check=True, capture_output=True)
	with open(SRC, 'rb') as src, open(path + '.apo.f32', 'wb') as out:
		subprocess.run(['wine', 'bluevoice_host.exe', WINE_DLL, path + PARAMS_EXT], stdin=src, stdout=out,
					   env=ENV, check=True, stderr=subprocess.DEVNULL)
	native = np.fromfile(path + '.native.f32', '<f4')
	apo = np.fromfile(path + '.apo.f32', '<f4')[APO_EXTRA:]
	n = min(len(native), len(apo)) - 1024
	diff = np.abs(native[1024:n] - apo[1024:n])
	signal = np.sqrt(np.mean(apo[1024:n] ** 2))
	return diff.max(), 20 * np.log10(np.sqrt(np.mean(diff ** 2)) / signal + 1e-30), np.mean(diff == 0)


if __name__ == '__main__':
	for case in (sys.argv[1:] or CASES):
		mx, rel, same = run(case, CASES[case])
		print(f'{case:20s} max diff {mx:.2e}   diff/signal {rel:7.1f} dB   identical {same * 100:6.2f}%', flush=True)
