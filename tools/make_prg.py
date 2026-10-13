"""Build a patched SP-808 OS and wrap it as SP808.PRG (the file the OS self-updates from).

SP808.PRG layout (from OS code at 0x127544 / 0x127670):
  +0  u32 0x00100000   flash start
  +4  u32 0x001C0000   flash end
  +8  0xC0000 bytes    image for 0x100000-0x1BFFFF

The OS accepts the file if (routine 0x127770):
  image[0] == 0x5A (it is `jmp 0x126616`, the OS entry),
  image[4:12] == "TS25ESYS",
  image[0:32] == image[0xBFFE0:0xC0000] (header copy at end of region).
No checksum. It prompts "Update System?" only if the image's version word
(image+0x0E) is newer than the running one, unless forced (HOLD held at boot).

usage: python -I make_prg.py raw.bin outdir
"""
import os, struct, sys

SIZE = 0xC0000
VER_HDR = (0x0E, 0xBFFEE)        # version word in header + its trailer copy
VER_CODE = 0x26670                # immediate of `mov.w #0x041a,r0` at 0x12666e (running version)

# (image offset, original bytes, new bytes)
PATCHES = [
    (0x626BE, b'System Edit Menu', b'JunksmithWizard!'),
]
NEW_VERSION = 1051               # shows as 1.05x; must be > running 1050 to get the prompt


def check(img):
    assert len(img) == SIZE
    assert img[0] == 0x5A, 'magic'
    assert img[4:12] == b'TS25ESYS', 'tag'
    assert img[0:32] == img[SIZE - 32:SIZE], 'header/trailer mismatch'


def main(raw, outdir):
    img = bytearray(open(raw, 'rb').read()[:SIZE])
    check(img)
    old_ver = struct.unpack('>H', img[0x0E:0x10])[0]
    assert old_ver == 1050 and img[VER_CODE:VER_CODE + 2] == b'\x04\x1a', 'unexpected base image'
    for off, old, new in PATCHES:
        assert len(old) == len(new) and img[off:off + len(old)] == old, 'patch mismatch @%x' % off
        img[off:off + len(new)] = new
    v = struct.pack('>H', NEW_VERSION)
    for off in VER_HDR:
        img[off:off + 2] = v
    img[VER_CODE:VER_CODE + 2] = v
    check(img)
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, 'sp808_mod.bin'), 'wb').write(img)
    prg = struct.pack('>II', 0x100000, 0x1C0000) + img
    open(os.path.join(outdir, 'SP808.PRG'), 'wb').write(prg)
    print('ok: version %d -> %d, %d patches, SP808.PRG %d bytes' % (old_ver, NEW_VERSION, len(PATCHES), len(prg)))


if __name__ == '__main__':
    main(*sys.argv[1:3])
