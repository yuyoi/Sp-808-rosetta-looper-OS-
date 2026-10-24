"""Build Roland-format MIDI update files (SP808#1-8.MID) for a patched SP-808 OS image, for the boot ROM's own update
mode (SP-808: power on holding STATUS + EFFECTS above fader A -> "Waiting MIDI..."; play the 8 files in order).

Roland's update is the template: every message, its timing and all control messages stay exactly as Roland made them;
data messages get the new image's bytes (re-packed 7-bit, new checksum). The boot ROM receiver (0x2D66) fills its
buffer (RAM 0x440000) with 0xFF, writes each data message at its nibble address (0x3024), and stops receiving as soon
as data reaches the end address 0x1C0000. Roland's files never send 0x16AD5E-0x1BFFD9, so changed bytes there (the CF
stub at 0x1BF000) go in extra messages placed before Roland's last data message (the header copy at 0x1BFFDA).
File bits (0x994C) come from the control messages, so "Data Not Enough!" sees the same 8 files.

usage: python -I tools/encode_upd.py <folder with Roland's SP808#1-8.MID> new_raw.bin|SP808.PRG outdir
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import decode_upd

FLASH, SIZE = 0x100000, 0xC0000
HDR = b'\x41\x00\x7C\x12'                       # the SP-808 boot ROM takes model 7C (or 00 0F), not the EX's 00 2B


def vlq(v):
    out = [v & 0x7F]
    while v > 0x7F: v >>= 7; out.append(0x80 | v & 0x7F)
    return bytes(reversed(out))


def read_track(path):
    """-> (header chunk bytes, [(delta, raw event bytes)]), format 0"""
    d = open(path, 'rb').read()
    hdr = d[:14]; i = 14
    assert d[i:i + 4] == b'MTrk'
    end = i + 8 + struct.unpack('>I', d[i + 4:i + 8])[0]; i += 8
    def rv():
        nonlocal i
        v = 0
        while True:
            c = d[i]; i += 1; v = v << 7 | c & 0x7F
            if c < 0x80: return v
    evs = []
    while i < end:
        dt = rv(); s = i
        if d[i] == 0xFF: i += 2; n = rv(); i += n
        elif d[i] in (0xF0, 0xF7): i += 1; n = rv(); i += n
        else: raise ValueError('channel event in an update file')
        evs.append((dt, d[s:i]))
    return hdr, evs


def write_track(path, hdr, evs):
    body = b''.join(vlq(dt) + raw for dt, raw in evs)
    open(path + '.tmp', 'wb').write(hdr + b'MTrk' + struct.pack('>I', len(body)) + body); os.replace(path + '.tmp', path)


def sysex_of(raw):                               # raw SMF event F0 <len> data..F7 -> data (without F0)
    i, n = 1, 0
    while True:
        c = raw[i]; i += 1; n = n << 7 | c & 0x7F
        if c < 0x80: break
    return raw[i:i + n]


def pack7(b):
    assert len(b) % 7 == 0
    out = bytearray()
    for g in range(0, len(b), 7):
        grp = b[g:g + 7]
        out += bytes(x & 0x7F for x in grp) + bytes([sum(0x40 >> k for k, x in enumerate(grp) if x & 0x80)])
    return bytes(out)


def data_msg(addr, payload):
    """flash address + payload (multiple of 7 bytes) -> SysEx data (no F0)"""
    a = addr - FLASH
    head = bytes([0, 0, 1, a >> 16]) + bytes([(a >> 12) & 15, (a >> 8) & 15, (a >> 4) & 15, a & 15])
    body = head + pack7(payload)
    return HDR + body + bytes([-sum(body) & 0x7F, 0xF7])


def parse_data(m):
    """SysEx data -> (flash address, payload length) for a data message, else None"""
    if not m.startswith(HDR) or m[4:7] != b'\x00\x00\x01': return None
    b = m[8:12]
    return FLASH + m[7] * 0x10000 + (b[0] << 12 | b[1] << 8 | b[2] << 4 | b[3]), (len(m) - 14) // 8 * 7


def coverage(tracks):
    covered = bytearray(SIZE)
    for _, evs in tracks:
        for _, raw in evs:
            p = parse_data(sysex_of(raw)) if raw[0] == 0xF0 else None
            if p: o = p[0] - FLASH; n = min(p[1], SIZE - o); covered[o:o + n] = b'\x01' * n
    return covered


def extras(folder, tracks, new):
    """changed bytes Roland's update never sends -> [(flash address, payload)], 196-byte chunks padded to 7"""
    roland, _ = decode_upd.decode(folder)
    covered = coverage(tracks)
    ch = [o for o in range(SIZE) if not covered[o] and new[o] != roland[o]]
    out, i = [], 0
    while i < len(ch):
        s = ch[i]; j = i
        while j + 1 < len(ch) and ch[j + 1] - s < 196: j += 1
        n = ch[j] + 1 - s; n += -n % 7
        out.append((FLASH + s, new[s:s + n])); i = j + 1
    return out


def load(folder):
    return [read_track(os.path.join(folder, 'SP808#%d.MID' % n)) for n in range(1, 9)]


def encode(folder, new, outdir):
    new = bytes(new[:SIZE]); tracks = load(folder); ext = extras(folder, tracks, new); changed = 0
    for n, (hdr, evs) in enumerate(tracks, 1):
        deltas = sorted(dt for dt, r in evs if r[0] == 0xF0); step = deltas[len(deltas) // 2]
        out = []
        for dt, raw in evs:
            m = sysex_of(raw) if raw[0] == 0xF0 else None
            p = parse_data(m) if m else None
            if p:
                a, ln = p; o = a - FLASH
                pay = new[o:o + ln] + decode_upd.unpack7(m[12:-2])[SIZE - o:] if o + ln > SIZE else new[o:o + ln]
                if o + ln >= SIZE:                               # the last data message: the extras go first
                    for ea, ep in ext:
                        mm = data_msg(ea, ep); out.append((step, b'\xF0' + vlq(len(mm)) + mm))
                    ext = []
                mm = data_msg(a, pay)
                if mm != m: changed += 1
                raw = b'\xF0' + vlq(len(mm)) + mm
            out.append((dt, raw))
        os.makedirs(outdir, exist_ok=True)
        write_track(os.path.join(outdir, 'SP808#%d.MID' % n), hdr, out)
    assert not ext, 'no end message found for the extra data'
    return changed


def expected(folder, new):
    """what the boot ROM's buffer should hold after receiving encode()'s files"""
    tracks = load(folder); covered = coverage(tracks)
    img = bytearray(x if c else 0xFF for x, c in zip(new[:SIZE], covered))
    for a, p in extras(folder, tracks, new): img[a - FLASH:a - FLASH + len(p)] = p
    return bytes(img)


if __name__ == '__main__':
    folder, raw, outdir = sys.argv[1:4]
    d = open(raw, 'rb').read()
    if len(d) == SIZE + 8: d = d[8:]                              # an SP808.PRG (8-byte header)
    n = encode(folder, d, outdir)
    print('%d data messages changed -> %s' % (n, outdir))
