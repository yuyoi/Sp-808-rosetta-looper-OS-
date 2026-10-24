"""CF beta: let Roland's SP-808 OS run on a plain ATA drive (a CF card on an IDE adapter) instead of the Iomega Zip.
Works on stock OS 1.05, stock SP-808EX OS 1.001 and Rosetta OS images (call sites are found by pattern).

Why it is needed (found in the emulator with ide_model.CFCard, see NOTES.md):
  The boot ROM's IDE driver already handles ATA: it detects a CF card (type 0 at 0x401014), reads its IDENTIFY and
  reads / writes its sectors. The OS disk check accepts an SP-808 image on it. But the OS also calls two boot ROM
  services that only exist for the Zip (ATAPI) and send an ATAPI PACKET whatever the drive is:
    0x4005A0  MODE SELECT (ROM 0x29C8), in every disk check (1.05: 0x105810, EX: 0x105524)
    0x4003BC  Iomega vendor command 0x0D (ROM 0x279E), twice, after many disk operations (1.05: 0x14840E/14)
  A CF card rejects the PACKET, the driver waits ~1M loops for an interrupt that never comes (about a second each on
  hardware), then leaves error 0002 in 0x40101E and clears 0x401081. That is the "boots but slow, won't sample" report.

The patch points those calls at a stub in free flash: on an ATA drive it returns success at once, on a Zip it jumps
to the real service, so Zip users see no change.

usage: python -I tools/cf_patch.py in_raw.bin out_raw.bin       (Rosetta Patcher uses stock() / patch_prg())
"""
import os, re, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h8asm import Asm

FLASH = 0x100000
STUB = 0x1BF000                        # zero in 1.05, EX 1.001 and Rosetta (Rosetta code ends well below)
DRIVE_TYPE = 0x401014                  # boot ROM: 0 = ATA (CF / HD), 1 = ATAPI (Zip)
ZIP_ONLY = {0x4003BC: 2, 0x4005A0: 1}  # RAM vector -> expected jsr count in the OS
TAG = b'CF beta'


def sites(img):
    return {v: [FLASH + m.start() for m in re.finditer(re.escape(b'\x5e' + v.to_bytes(3, 'big')), img[:0xC0000])]
            for v in ZIP_ONLY}


def stub():
    a = Asm(STUB)
    for v in ZIP_ONLY:
        a.label('z%X' % v)
        a.mov_b_from_abs(DRIVE_TYPE, 'r1l')                      # r1 is scratch here: the ROM services clobber it too
        a.beq('a%X' % v)
        a.jmp(v)                                                 # Zip: the real service
        a.label('a%X' % v)
        a.mov_w_imm(1, 0)                                        # ATA: nothing to do, report success
        a.rts()
    a.label('tag'); a.string(TAG.decode())
    return a.assemble(), a.labels


def patch(img):
    img = bytearray(img)
    found = sites(img)
    if all(not s for s in found.values()) and img[STUB - FLASH:STUB - FLASH + 4] != bytes(4):
        raise ValueError('already CF patched')
    for v, n in ZIP_ONLY.items():
        if len(found[v]) != n:
            raise ValueError('expected %d calls to %06X, found %s: unknown OS' % (n, v, [hex(s) for s in found[v]]))
    code, labels = stub()
    o = STUB - FLASH
    if any(img[o:o + len(code) + 16]):
        raise ValueError('stub area %06X is not free in this image' % STUB)
    img[o:o + len(code)] = code
    for v, ss in found.items():
        for s in ss:
            img[s - FLASH + 1:s - FLASH + 4] = labels['z%X' % v].to_bytes(3, 'big')
    return bytes(img), found


def is_patched(img):
    return TAG in img[STUB - FLASH:STUB - FLASH + 0x100]


# ---- stock Roland OS + CF, as SP808.PRG (layout and accept rules: make_prg.py) ----
SIZE = 0xC0000
VER_HDR = (0x0E, 0xBFFEE)                                         # version word in the header + its trailer copy
STOCK = {1050: ('SP-808 OS 1.05', 0x26670, 1051),                # running-version immediate (mov.w #ver,r0), new version
         1001: ('SP-808EX OS 1.001', 0x2CCAE, 1002)}


def version(img):
    return struct.unpack('>H', img[0x0E:0x10])[0]


def stock(img):
    """stock Roland image -> (CF-patched image with a bumped version, OS name, old version, new version)"""
    img = bytearray(img[:SIZE])
    ver = version(img)
    if ver not in STOCK: raise ValueError('OS version %d: CF beta knows 1.05 (1050) and EX 1.001 (1001)' % ver)
    name, code, new = STOCK[ver]
    if img[0] != 0x5A or img[4:12] != b'TS25ESYS' or img[:32] != img[SIZE - 32:] or \
            img[code:code + 2] != struct.pack('>H', ver):
        raise ValueError('not a clean Roland %s image' % name)
    out = bytearray(patch(img)[0])
    for off in VER_HDR + (code,): out[off:off + 2] = struct.pack('>H', new)
    assert out[:32] == out[SIZE - 32:]
    return bytes(out), name, ver, new


def prg(img):
    return struct.pack('>II', 0x100000, 0x1C0000) + bytes(img[:SIZE])


def patch_prg(path):
    """CF-patch an existing SP808.PRG in place (Rosetta builds)"""
    d = open(path, 'rb').read()
    out = prg(patch(d[8:8 + SIZE])[0])
    open(path + '.tmp', 'wb').write(out); os.replace(path + '.tmp', path)


def main(src, dst):
    out, found = patch(open(src, 'rb').read())
    open(dst + '.tmp', 'wb').write(out); os.replace(dst + '.tmp', dst)
    print('CF beta patch: %s -> %s, retargeted %s' % (src, dst, {hex(v): [hex(s) for s in ss] for v, ss in found.items()}))


if __name__ == '__main__':
    main(*sys.argv[1:])
