"""Decode Roland's SP-808 OS update (SP808#1.MID .. SP808#8.MID, from SP808v1050.zip) into the flash image.

The update is 8 Standard MIDI Files full of Roland DT1 SysEx (F0 41 00 7C 12 addr body sum F7).
Data messages have address 00 00 01 PP (PP = 64 KB page of the OS flash at 0x100000) and a body of
  4 nibbles  = 16-bit byte offset inside the page
  224 bytes  = 7-bit packed data: groups of 8 = 7 data bytes + 1 byte of their top bits
               (bit 6 of that byte belongs to the first data byte, bit 0 to the seventh) -> 196 bytes
Address 01 xx xx xx messages are control (start/end). No compression, no encryption.

usage: python -I tools/decode_upd.py <folder with SP808#1-8.MID> sp808_v1050_raw.bin
"""
import os, sys


def vlq(b, i):
    v = 0
    while True:
        c = b[i]; i += 1; v = (v << 7) | (c & 0x7F)
        if c < 0x80: return v, i


def sysex(data):
    i = 0
    while True:
        i = data.find(b'\xF0', i)
        if i < 0: return
        n, j = vlq(data, i + 1)
        yield data[j:j + n]
        i = j + n


def unpack7(b):
    out = bytearray()
    for g in range(0, len(b), 8):
        grp = b[g:g + 8]; top = grp[-1]
        for k, x in enumerate(grp[:-1]):
            out.append(x | (0x80 if top & (0x40 >> k) else 0))
    return out


def decode(folder):
    img = bytearray(); chunks = 0
    for n in range(1, 9):
        data = open(os.path.join(folder, 'SP808#%d.MID' % n), 'rb').read()
        for m in sysex(data):
            if m[:4] != b'\x41\x00\x7C\x12' or m[-1] != 0xF7: continue
            addr, body, ck = m[4:8], m[8:-2], m[-2]
            assert (sum(m[4:-2]) + ck) & 0x7F == 0, 'checksum'
            if addr[:3] != b'\x00\x00\x01': continue          # control message
            off = (body[0] << 12) | (body[1] << 8) | (body[2] << 4) | body[3]
            payload = unpack7(body[4:])
            at = addr[3] * 0x10000 + off
            if len(img) < at + len(payload): img.extend(bytes(at + len(payload) - len(img)))
            img[at:at + len(payload)] = payload; chunks += 1
    return bytes(img), chunks


if __name__ == '__main__':
    img, chunks = decode(sys.argv[1])
    open(sys.argv[2], 'wb').write(img)
    print('%d data messages -> %d bytes (OS image at 0x100000, header "%s")' % (chunks, len(img), img[4:12].decode('ascii', 'replace')))
