"""Reference R-DAC decoder/encoder: runs the SP-808 boot ROM's own frame codec (API 058 decode at 0x0055B2,
API 057 encode at 0x00309C) inside the H8S emulator. Needs dump/BOOTROM.BIN (Roland code, not in the repo).

Frame: 12 bytes = 16 samples of one channel (two interleaved 6-byte half-frames of 8 samples each), decoded with a
16-bit state word carried from frame to frame (starts at 0). Stereo units are L frame then R frame (24 bytes).
Take files: 32 KB blocks, 32760 bytes of frames per block (1365 stereo / 2730 mono units), 8 bytes unused.

usage: python -I tools/rdac_emu.py disk.img SONG0000.VS2 pad_number out.wav   (bank 1)
       python -I tools/rdac_emu.py disk.img SONG0000.VS2 wave:83 out.wav       (whole take, mono assumed)
"""
import os, struct, sys, wave
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import h8emu

HERE = os.path.dirname(os.path.abspath(__file__))
DECODE, ENCODE = 0x0055B2, 0x00309C
IN_BUF, OUT_BUF = 0x440000, 0x441000


class Codec:
    def __init__(self, bootrom=os.path.join(HERE, '..', 'dump', 'BOOTROM.BIN')):
        self.e = e = h8emu.Emu(bytes(0x100))              # no OS needed
        e.boot = open(bootrom, 'rb').read(); e.code_lo = 0; e.code_hi = 0x1000000
        e.flash = bytearray(0)                             # keep the flash region empty
        self.steps = 0

    def decode_frame(self, frame, state):
        """12 bytes -> (16 signed samples, new state)."""
        e = self.e
        for i, b in enumerate(frame): e.wb(IN_BUF + i, b)
        for i in range(256): e.wb(OUT_BUF + i, 0)
        e.s32(0, IN_BUF); e.s32(1, OUT_BUF); e.s16(2, state & 0xFFFF)
        e.steps = 0; e.call(DECODE, sp=0x43F000, limit=200_000); self.steps += e.steps
        out = [struct.unpack('>h', bytes((e.rb(OUT_BUF + 16 * k), e.rb(OUT_BUF + 16 * k + 1))))[0] for k in range(16)]
        return out, e.g16(2), e.g32(0) - IN_BUF

    def encode_frame(self, samples, state):
        """16 signed samples -> (12 bytes, new state). Input layout as the record DMA buffer: stride 4 bytes."""
        e = self.e
        for i, s in enumerate(samples):
            b = struct.pack('>h', max(-32768, min(32767, s))); e.wb(IN_BUF + 4 * i, b[0]); e.wb(IN_BUF + 4 * i + 1, b[1])
        for i in range(32): e.wb(OUT_BUF + i, 0)
        e.s32(0, IN_BUF); e.s32(1, OUT_BUF); e.s16(2, state & 0xFFFF)
        e.steps = 0; e.call(ENCODE, sp=0x43F000, limit=200_000); self.steps += e.steps
        return bytes(e.rb(OUT_BUF + i) for i in range(12)), e.g16(2)


def unit_offset(unit, mono):
    per_block = 2730 if mono else 1365
    return (unit // per_block) * 32768 + (unit % per_block) * (12 if mono else 24)


def decode_units(codec, data, start, end, mono, progress=None):
    """Decode units start..end of a take -> list of channels (lists of samples)."""
    chans = [[], []] if not mono else [[]]
    states = [0, 0]
    for u in range(start, end):
        o = unit_offset(u, mono)
        for c in range(len(chans)):
            fr = data[o + 12 * c:o + 12 * c + 12]
            if len(fr) < 12: break
            smp, states[c], used = codec.decode_frame(fr, states[c])
            chans[c].extend(smp)
        if progress and (u - start) % 500 == 0: progress(u - start, end - start)
    return chans


def write_wav(path, chans, rate=44100):
    n = len(chans)
    with wave.open(path, 'wb') as w:
        w.setnchannels(n); w.setsampwidth(2); w.setframerate(rate)
        frames = bytearray()
        for i in range(len(chans[0])):
            for c in range(n): frames += struct.pack('<h', max(-32768, min(32767, chans[c][i])))
        w.writeframes(bytes(frames))


def main(img_path, song, what, out):
    sys.path.insert(0, os.path.join(HERE, '..', '..', 'sp-808-disk-studio'))
    from sp808studio import image, vs2
    im = image.Image(img_path)
    s = [x for x in vs2.songs(im) if x.name.upper() == song.upper()][0]
    codec = Codec()
    if what.startswith('wave:'):
        w = int(what[5:]); data = s.take_bytes(w); mono = True
        start, end = 0, len(data) // 32768 * 2730
    else:
        p = s.pads[0][int(what) - 1]; data = s.take_bytes(p.wave); mono = p.mono; start, end = p.start, p.end
        print(p)
    import time; t = time.time()
    chans = decode_units(codec, data, start, end, mono, lambda a, b: print('  %d/%d units' % (a, b)))
    write_wav(out, chans)
    peak = max(abs(x) for x in chans[0])
    print('wrote %s: %d samples, %d ch, peak %d, %.0f emulated instructions per frame, %.1f s' % (
        out, len(chans[0]), len(chans), peak, codec.steps / max(1, (end - start) * len(chans)), time.time() - t))


if __name__ == '__main__':
    main(*sys.argv[1:5])
