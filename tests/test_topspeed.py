"""Top-speed finder: the game eases your speed toward a max-speed setting stored in memory."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np
import ps2core as core

rng = np.random.default_rng(5)
MEM = np.zeros(0x400000, np.uint8)
FV = MEM.view("<f4")
SPEED, CAP, HUD = 0x100010, 0x200040, 0x300000
FV[CAP // 4] = 7.5                                              # the setting
decoys = rng.choice(np.arange(0x1000, 0xF0000, 4), 300, replace=False)
FV[decoys // 4] = 7.5                                           # same number, does nothing
FV[0x50000 // 4] = 7.5 / 60                                     # per-frame copy (does nothing either)
running = {"on": False}


def frame():
    target = float(FV[CAP // 4]) if running["on"] else 0.0
    sp = float(FV[SPEED // 4])
    FV[SPEED // 4] = sp + (target - sp) * 0.2
    FV[HUD // 4] = FV[SPEED // 4] * 3.6                       # km/h on the HUD (changes while running)


def run(frames):
    seen = []
    for _ in range(frames):
        frame()
        seen.append(float(FV[SPEED // 4]))
    return seen


def read(a, vt):
    return core.decode(vt, MEM[a:a + core.TYPES[vt][2]].tobytes())


def write(a, vt, v):
    raw = core.encode(vt, v)
    MEM[a:a + len(raw)] = np.frombuffer(raw, np.uint8)


run(30)
still = MEM.copy()
running["on"] = True
samples = run(180)
moving = MEM.copy()
top = core.TopSpeedHunt.top_speed(samples[120:])
assert abs(top - 7.5) < 0.05, top
cands = core.TopSpeedHunt.find_candidates(still, moving, top, (SPEED, "float"))
print(len(cands), "candidates, first:", cands[:3])
assert (CAP, "float") in cands and (SPEED, "float") not in cands and (0x50000, "float") in cands
assert all(a != HUD for a, _ in cands)                         # it changed while running: not a setting

hunt = core.TopSpeedHunt((SPEED, "float"), top, cands)
rounds = 0
while not hunt.done and rounds < 40:
    rounds += 1
    group = hunt.next_group()
    orig = {k: read(*k) for k in group}
    seen = []
    for _ in range(90):                                         # ~1.5 s with the group doubled
        for (a, vt), v in orig.items():
            write(a, vt, hunt.boosted(v, vt))
        frame()
        seen.append(float(FV[SPEED // 4]))
    for (a, vt), v in orig.items():
        write(a, vt, v)
    verdict = hunt.judge(seen)
    hunt.answer(verdict)
    run(120)                                                    # back down to normal
print("rounds:", rounds, "found:", hunt.found, hunt.rounds[-3:])
assert hunt.found == (CAP, "float") and rounds <= 12
assert abs(read(CAP, "float") - 7.5) < 1e-6 and all(abs(FV[d // 4] - 7.5) < 1e-6 for d in decoys)  # all restored

# standing still during a test = "not sure", never a wrong answer
h2 = core.TopSpeedHunt((SPEED, "float"), 7.5, [(CAP, "float"), (0x1000, "float")])
h2.next_group()
assert h2.judge([0.1, 0.0, 0.2, 0.1, 0.0]) is None
assert h2.judge([7.4, 7.5, 7.5, 7.5]) is False and h2.judge([7.5, 9, 12, 14]) is True
print("TOP SPEED TESTS PASSED")
