"""Drive the SP-808 (Rosetta OS v1.98+) from the PC over MIDI and record its audio: hardware-in-the-loop tests.
Windows only, no extra packages (winmm through ctypes).

Firmware side (v1.98): a note on MIDI channel 16 = a press of key code <note> (0x00-0x7F), channel 15 = key code
0x80 + note; velocity 64+ = with SHIFT; note-off = the release. The OS's key dispatcher takes these before the panel,
so they act exactly like the real buttons (looper, menus, pads...). Cables: PC MIDI OUT -> SP-808 MIDI IN, SP-808
outputs -> the interface inputs (for --rec).

usage:
  python -I tools/sp808_midi.py ports                                   list MIDI outs and audio inputs
  python -I tools/sp808_midi.py key PADSMPL [--hold 120] [--shift]       one tap
  python -I tools/sp808_midi.py run "PADSMPL 120; wait 4000; PADSMPL 120; wait 4000" [--rec out.wav] [--tail 2000]
      steps: KEY [hold_ms] (tap) | down KEY | up KEY | wait MS | SHIFT+KEY [hold_ms]
      --rec records the audio input from before the first step to --tail ms after the last; out.json gets every
      event with its time in ms and its sample index in the WAV (from the input device's own sample counter).
  options: --midi SUBSTR (default: the first port with "focusrite" / "scarlett" in its name, else port 0)
           --audio SUBSTR (default "focusrite"), --rate 48000
keys: PAD1-PAD16, PADSMPL, PADBANK, UP, DOWN, LEFT, RIGHT, ENTER, EXIT, SONG, SYSTEM, SAMPLE, LOC1-LOC4, or 0xNN.
"""
import ctypes, json, struct, sys, time, wave
from ctypes import wintypes as W

KEYS = dict(PADSMPL=0x22, PADBANK=0x20, UP=0x70, DOWN=0x71, LEFT=0x72, RIGHT=0x73, EXIT=0xB0, ENTER=0xB1,
            SONG=0x80, SYSTEM=0x81, SAMPLE=0x82, **{'PAD%d' % (i + 1): 0x10 + i for i in range(16)},
            **{'LOC%d' % (i + 1): 0x40 + i for i in range(4)})
wm = ctypes.WinDLL('winmm')


class MIDIOUTCAPS(ctypes.Structure):
    _fields_ = [('wMid', W.WORD), ('wPid', W.WORD), ('vDriverVersion', W.UINT), ('szPname', W.WCHAR * 32),
                ('wTechnology', W.WORD), ('wVoices', W.WORD), ('wNotes', W.WORD), ('wChannelMask', W.WORD),
                ('dwSupport', W.DWORD)]


class WAVEINCAPS(ctypes.Structure):
    _fields_ = [('wMid', W.WORD), ('wPid', W.WORD), ('vDriverVersion', W.UINT), ('szPname', W.WCHAR * 32),
                ('dwFormats', W.DWORD), ('wChannels', W.WORD), ('wReserved1', W.WORD)]


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [('wFormatTag', W.WORD), ('nChannels', W.WORD), ('nSamplesPerSec', W.DWORD),
                ('nAvgBytesPerSec', W.DWORD), ('nBlockAlign', W.WORD), ('wBitsPerSample', W.WORD), ('cbSize', W.WORD)]


class WAVEHDR(ctypes.Structure):
    pass
WAVEHDR._fields_ = [('lpData', ctypes.c_void_p), ('dwBufferLength', W.DWORD), ('dwBytesRecorded', W.DWORD),
                    ('dwUser', ctypes.c_size_t), ('dwFlags', W.DWORD), ('dwLoops', W.DWORD),
                    ('lpNext', ctypes.POINTER(WAVEHDR)), ('reserved', ctypes.c_size_t)]


class MMTIME(ctypes.Structure):
    _fields_ = [('wType', W.UINT), ('u', W.DWORD * 2)]


def midi_outs():
    out = []
    for i in range(wm.midiOutGetNumDevs()):
        c = MIDIOUTCAPS(); wm.midiOutGetDevCapsW(i, ctypes.byref(c), ctypes.sizeof(c)); out.append(c.szPname)
    return out


def wave_ins():
    out = []
    for i in range(wm.waveInGetNumDevs()):
        c = WAVEINCAPS(); wm.waveInGetDevCapsW(i, ctypes.byref(c), ctypes.sizeof(c)); out.append(c.szPname)
    return out


def pick(names, sub, defaults=()):
    for s in ([sub] if sub else list(defaults)):
        for i, n in enumerate(names):
            if s.lower() in n.lower(): return i
    if sub: sys.exit('no device matching %r in %s' % (sub, names))
    return 0 if names else sys.exit('no devices')


class Midi:
    def __init__(self, sub):
        names = midi_outs(); self.idx = pick(names, sub, ('focusrite', 'scarlett'))
        self.name, self.h = names[self.idx], W.HANDLE()
        r = wm.midiOutOpen(ctypes.byref(self.h), self.idx, 0, 0, 0)
        if r: sys.exit('midiOutOpen(%s) failed: %d (port in use by another program?)' % (self.name, r))
    def send(self, status, d1, d2): wm.midiOutShortMsg(self.h, status | d1 << 8 | d2 << 16)
    def key(self, code, down, shift=False):          # channel 16 = codes 0x00-0x7F, channel 15 = 0x80-0xFF
        ch = 15 if code < 0x80 else 14
        if down: self.send(0x90 | ch, code & 0x7F, 96 if shift else 32)
        else: self.send(0x80 | ch, code & 0x7F, 0)
    def close(self): wm.midiOutClose(self.h)      # no midiOutReset: its note-offs on ch 15/16 = key releases


class Rec:                                            # waveIn, polled (CALLBACK_NULL), 16-bit stereo
    def __init__(self, sub, rate):
        names = wave_ins(); self.idx = pick(names, sub, ('focusrite', 'scarlett'))
        self.name, self.rate, self.h = names[self.idx], rate, W.HANDLE()
        f = WAVEFORMATEX(1, 2, rate, rate * 4, 4, 16, 0)
        r = wm.waveInOpen(ctypes.byref(self.h), self.idx, ctypes.byref(f), 0, 0, 0)
        if r: sys.exit('waveInOpen(%s, %d Hz) failed: %d' % (self.name, rate, r))
        self.bufs, self.hdrs, self.data = [], [], bytearray()
        n = rate // 25 * 4                             # 40 ms buffers
        for _ in range(16):
            b = ctypes.create_string_buffer(n); h = WAVEHDR(ctypes.addressof(b), n, 0, 0, 0, 0, None, 0)
            wm.waveInPrepareHeader(self.h, ctypes.byref(h), ctypes.sizeof(h)); wm.waveInAddBuffer(self.h, ctypes.byref(h), ctypes.sizeof(h))
            self.bufs.append(b); self.hdrs.append(h)
        self.next = 0
        wm.waveInStart(self.h)
    def pos(self):                                     # samples captured so far (the device's own counter)
        t = MMTIME(); t.wType = 2; wm.waveInGetPosition(self.h, ctypes.byref(t), ctypes.sizeof(t))
        return t.u[0] if t.wType == 2 else -1
    def poll(self):
        while self.hdrs[self.next].dwFlags & 1:        # WHDR_DONE, in order
            h = self.hdrs[self.next]
            self.data += ctypes.string_at(h.lpData, h.dwBytesRecorded)
            h.dwFlags &= ~1; h.dwBytesRecorded = 0
            wm.waveInAddBuffer(self.h, ctypes.byref(h), ctypes.sizeof(h))
            self.next = (self.next + 1) % len(self.hdrs)
    def stop(self, path):
        self.poll(); wm.waveInReset(self.h); self.poll()
        for h in self.hdrs: wm.waveInUnprepareHeader(self.h, ctypes.byref(h), ctypes.sizeof(h))
        wm.waveInClose(self.h)
        with wave.open(path, 'wb') as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(self.rate); w.writeframes(bytes(self.data))


def code_of(name):
    shift = name.upper().startswith('SHIFT+')
    n = name[6:] if shift else name
    c = int(n, 16) if n.lower().startswith('0x') else KEYS.get(n.upper())
    if c is None: sys.exit('unknown key %r (known: %s)' % (n, ' '.join(KEYS)))
    return c, shift


def run(steps, midi, rec=None, tail=0):
    log, t0 = [], time.perf_counter()
    def wait(ms):
        end = time.perf_counter() + ms / 1000
        while time.perf_counter() < end:
            if rec: rec.poll()
            time.sleep(0.002)
    def ev(kind, name, code=None):
        log.append(dict(t_ms=round((time.perf_counter() - t0) * 1000, 1), ev=kind, key=name, code=code,
                        sample=rec.pos() if rec else None))
    for st in [s.strip() for s in steps.replace('\n', ';').split(';') if s.strip()]:
        w = st.split()
        if w[0].lower() == 'wait': wait(float(w[1])); continue
        if w[0].lower() in ('down', 'up'):
            c, sh = code_of(w[1]); midi.key(c, w[0].lower() == 'down', sh); ev(w[0].lower(), w[1], c); continue
        c, sh = code_of(w[0]); hold = float(w[1]) if len(w) > 1 else 120
        midi.key(c, True, sh); ev('down', w[0], c); wait(hold); midi.key(c, False, sh); ev('up', w[0], c)
    if tail: wait(tail)
    return log


def main():
    a = sys.argv[1:]
    def opt(name, default=None, flag=False):
        if name not in a: return default
        i = a.index(name)
        if flag: a.pop(i); return True
        v = a[i + 1]; del a[i:i + 2]; return v
    msub, asub, rate = opt('--midi'), opt('--audio'), int(opt('--rate', 48000))
    recp, tail, hold, shift = opt('--rec'), float(opt('--tail', 2000)), opt('--hold', '120'), opt('--shift', flag=True)
    if not a or a[0] == 'ports':
        print('MIDI out:', *['  %d: %s' % x for x in enumerate(midi_outs())], sep='\n')
        print('audio in:', *['  %d: %s' % x for x in enumerate(wave_ins())], sep='\n'); return
    midi = Midi(msub); print('MIDI ->', midi.name)
    try:
        if a[0] == 'key':
            print(run(('SHIFT+' if shift else '') + a[1] + ' ' + hold, midi))
        elif a[0] == 'run':
            rec = Rec(asub, rate) if recp else None
            if rec: print('recording', rec.name, rate, 'Hz ->', recp); time.sleep(0.3)
            log = run(a[1], midi, rec, tail if rec else 0)
            if rec:
                rec.stop(recp); json.dump(dict(rate=rate, device=rec.name, midi=midi.name, events=log),
                                          open(recp.rsplit('.', 1)[0] + '.json', 'w'), indent=1)
            for x in log: print(x)
        else: sys.exit(__doc__)
    finally:
        midi.close()


if __name__ == '__main__':
    main()
