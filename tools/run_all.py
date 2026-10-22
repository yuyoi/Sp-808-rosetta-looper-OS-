"""Run the emulator test suite on a build, several tests at once, and compare with a baseline.
usage: python -I tools/run_all.py [--bin work/build_v10/sp808_v10.bin] [--out work/runs] [--base work/baseline_v197]
                                  [-j 3] [--quick] [test_x ...]
Each test's output goes to <out>/<test>.txt (+ .png). The summary shows exit code, minutes, odd word/long accesses
(any = wrong bytes on the real H8S, see NOTES v1.95) and how many lines differ from <base>/<test>.txt. Timestamps
shift whenever the code size changes, so read the diff, don't count it. test_v10 (the full KEYS suite) takes ~1 h."""
import argparse, concurrent.futures as cf, difflib, os, re, runpy, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUICK = ['test_lfo', 'test_mfx', 'test_fx', 'test_route', 'test_kset', 'test_arp', 'test_padled', 'test_voice', 'test_synth',
         'test_mfx_mod', 'test_mfx_vocoder', 'test_remote', 'test_loop_timing']
FULL = ['test_v10'] + QUICK                     # longest first


def one(test, image, png):                     # child process: one test, counting every emulator's odd accesses
    sys.path.insert(0, HERE)
    import h8emu
    emus, init = [], h8emu.Emu.__init__
    def rec(self, *a, **k):
        init(self, *a, **k); emus.append(self)
    h8emu.Emu.__init__ = rec
    sys.argv = [os.path.join(HERE, test + '.py'), image, png]
    try:
        f = runpy.run_path(sys.argv[0], run_name='run_all_child')['main']
        f(*(image, png)[:f.__code__.co_argcount])           # some tests take only the image (test_padled, test_voice)
    finally:
        odd = sorted(set().union(*(e.odd for e in emus))) if emus else []
        print('[run_all] emus %d odd accesses %d %s' % (len(emus), len(odd), ['pc %06X @%06X' % x for x in odd[:8]]))


def main():
    if sys.argv[1:2] == ['--one']:
        return one(*sys.argv[2:5])
    ap = argparse.ArgumentParser()
    ap.add_argument('--bin', default=os.path.join(ROOT, 'work', 'build_v10', 'sp808_v10.bin'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'work', 'runs'))
    ap.add_argument('--base', default=os.path.join(ROOT, 'work', 'baseline_v197'))
    ap.add_argument('-j', type=int, default=3)
    ap.add_argument('--quick', action='store_true', help='skip test_v10 (the ~1 h KEYS suite)')
    ap.add_argument('tests', nargs='*')
    o = ap.parse_args()
    tests = o.tests or (QUICK if o.quick else FULL)
    image, out = os.path.abspath(o.bin), os.path.abspath(o.out)
    os.makedirs(out, exist_ok=True)

    def run(t):
        t0 = time.time()
        with open(os.path.join(out, t + '.txt'), 'w') as f:
            r = subprocess.run([sys.executable, '-I', os.path.abspath(__file__), '--one', t, image,
                                os.path.join(out, t + '.png')], stdout=f, stderr=subprocess.STDOUT, cwd=HERE)
        return t, r.returncode, (time.time() - t0) / 60

    bad = 0
    print('%-12s %4s %6s %5s %s' % ('test', 'exit', 'min', 'odd', 'lines differing from baseline'))
    with cf.ThreadPoolExecutor(o.j) as ex:
        for fu in cf.as_completed([ex.submit(run, t) for t in tests]):
            t, rc, mins = fu.result()
            txt = open(os.path.join(out, t + '.txt'), errors='replace').read()
            m = re.search(r'\[run_all\] emus \d+ odd accesses (\d+)', txt)
            odd = int(m.group(1)) if m else -1
            bp = os.path.join(o.base, t + '.txt')
            if os.path.exists(bp):
                strip = lambda s: [l for l in s.splitlines() if not l.startswith('[run_all]') and not l.endswith('.png')]
                d = [l for l in difflib.unified_diff(strip(open(bp, errors='replace').read()), strip(txt), n=0, lineterm='')
                     if l[:1] in '+-' and not l.startswith(('+++', '---'))]
                diff = '%d' % len(d)
            else:
                diff = 'no baseline'
            bad += rc != 0 or odd != 0
            print('%-12s %4d %6.1f %5s %s' % (t, rc, mins, odd if odd >= 0 else '?', diff), flush=True)
    print('ALL RAN CLEAN (exit 0, no odd accesses): now read the diffs' if not bad else '%d TEST(S) FAILED OR HIT ODD ACCESSES' % bad)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
