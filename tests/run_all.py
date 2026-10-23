"""Run every test:  python tests/run_all.py   (GUI tests need a display; on Linux use xvfb-run)."""
import os, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
fast = [f for f in sorted(os.listdir(here)) if f.startswith("test_") and not f.startswith("test_gui")]
gui = [f for f in sorted(os.listdir(here)) if f.startswith("test_gui")]
only_fast = "--fast" in sys.argv
bad = []
for f in fast + ([] if only_fast else gui):
    args = [sys.executable, os.path.join(here, f)] + (["zone"] if f == "test_predict2.py" else [])
    r = subprocess.run(args, capture_output=True, text=True, timeout=900)
    ok = r.returncode == 0 and "PASSED" in r.stdout
    print(("ok   " if ok else "FAIL ") + f)
    if not ok:
        bad.append(f)
        print((r.stdout + r.stderr)[-1500:])
print("ALL PASSED" if not bad else f"{len(bad)} failed: {bad}")
sys.exit(1 if bad else 0)
