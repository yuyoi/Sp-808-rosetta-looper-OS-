"""Who references an address? Code (calls / immediates / data refs from xref.pkl) and raw 32-bit pointers in the image.

Usage: python -I tools/q.py 16147B 1406FE ...
"""
import os, pickle, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
calls, imms, ins, drefs = pickle.load(open(os.path.join(HERE, 'xref.pkl'), 'rb'))
img = open(os.path.join(HERE, '..', 'sp808_v1050_raw.bin'), 'rb').read()
BASE = 0x100000

for arg in sys.argv[1:]:
    a = int(arg, 16)
    print('== %06X' % a)
    for name, tab in (('call', calls), ('imm', imms), ('dref', drefs)):
        hits = tab.get(a, [])
        if hits: print('  %-5s' % name, ' '.join('%06X' % h for h in hits[:40]), '...' if len(hits) > 40 else '')
    pat = struct.pack('>I', a)
    o = img.find(pat); ptrs = []
    while o >= 0 and len(ptrs) < 40:
        ptrs.append(o + BASE); o = img.find(pat, o + 1)
    if ptrs: print('  ptr  ', ' '.join('%06X' % p for p in ptrs))
