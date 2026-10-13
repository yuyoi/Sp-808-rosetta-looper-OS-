"""JSW v0.6b = v0.6 (MPC mode flow, unchanged) + Roland-chan boot animation (tools/bootanim.py).

usage: python -I build_v06b.py raw.bin outdir
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_v06 as v06
import bootanim
from make_prg import check, SIZE, VER_HDR, VER_CODE

VERSION = 1058
ANIM_BASE = 0x170000


def main(raw, outdir):
    img = bytearray(open(raw, 'rb').read()[:SIZE]); check(img)
    assert struct.unpack('>H', img[0x0E:0x10])[0] == 1050
    o = 0x626BE; assert img[o:o + 16] == b'System Edit Menu'; img[o:o + 16] = b'JunksmithWizard!'
    blob, labels = v06.build()
    off = v06.CODE_BASE - 0x100000
    assert not any(img[off:off + len(blob)]), 'target flash not empty'
    assert v06.CODE_BASE + len(blob) < ANIM_BASE
    img[off:off + len(blob)] = blob

    def patch_screen(idx, want_handler, new_handler, params=None, page=None):
        e = v06.SCREEN_TABLE - 0x100000 + 22 * idx
        fl, h, pa, pg, x, par = struct.unpack('>IIIIIH', img[e:e + 22])
        assert h == want_handler, 'screen %x handler %x' % (idx, h)
        img[e:e + 22] = struct.pack('>IIIIIH', fl, new_handler,
                                    pa if params is None else params, pg if page is None else page, x, par)
    patch_screen(v06.SCREEN, 0x13D224, labels['menu'], params=0xFFFFFFFF, page=0)
    patch_screen(v06.SCR_RECORD, v06.STOCK_SCR22, labels['w22'])
    patch_screen(v06.SCR_DONE, v06.STOCK_SCR23, labels['w23'])
    for grp, stock, lbl in ((1, v06.STOCK_G1, 'g1'), (2, v06.STOCK_G2, 'g2'), (8, v06.STOCK_G8, 'g8')):
        k = v06.KEYGROUP_TABLE - 0x100000 + 4 * grp
        assert struct.unpack('>I', img[k:k + 4])[0] == stock
        img[k:k + 4] = struct.pack('>I', labels[lbl])

    ablob, alabels = bootanim.patch(img, ANIM_BASE)

    v = struct.pack('>H', VERSION)
    for o in VER_HDR: img[o:o + 2] = v
    img[VER_CODE:VER_CODE + 2] = v
    check(img)
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, 'sp808_v06b.bin'), 'wb').write(img)
    open(os.path.join(outdir, 'SP808.PRG'), 'wb').write(struct.pack('>II', 0x100000, 0x1C0000) + img)
    print('v0.6b built: v0.6 code %d bytes at 0x%X + boot anim %d bytes at 0x%X, version %d'
          % (len(blob), v06.CODE_BASE, len(ablob), ANIM_BASE, VERSION))
    print('  anim 0x%X  table 0x%X' % (alabels['anim'], alabels['anim_table']))


if __name__ == '__main__':
    main(*sys.argv[1:3])
