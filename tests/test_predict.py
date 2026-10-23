import sys, time
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import numpy as np
import ps2core as c

rng = np.random.default_rng(21)
NF = c.EE_SIZE // 4
mem = np.zeros(c.EE_SIZE, dtype=np.uint8)
mem[rng.integers(0, c.EE_SIZE, 1_500_000)] = rng.integers(0, 256, 1_500_000, dtype=np.uint8)
fv = mem.view("<f4")
anim = rng.choice(NF, 120_000, replace=False)
osc = rng.choice(NF, 40_000, replace=False)
osc_p = rng.uniform(0.3, 3, len(osc)); osc_ph = rng.uniform(0, 6.3, len(osc))
BALL = 3_000_000            # x, y, z (z = toward the plate)
TGT = 3_100_000             # CPU's chosen plate target x, y  (the thing we want)
MITT = 3_100_040            # catcher's mitt: drifts toward the target during the wind-up
SPEEDPICK = 3_100_080       # random pitch speed choice: decided at the same time, unrelated
keep_clear = np.r_[BALL - 8:BALL + 8, TGT - 2:TGT + 4, MITT - 2:MITT + 4, SPEEDPICK - 2:SPEEDPICK + 2]
anim = np.setdiff1d(anim, keep_clear); osc = osc[~np.isin(osc, keep_clear)]
osc_p, osc_ph = osc_p[:len(osc)], osc_ph[:len(osc)]

CYCLE, WIND = 4.5, 1.8      # seconds per pitch, wind-up length
pitches = []
for k in range(14):
    s = 1.0 + k * CYCLE
    pitches.append({"start": s, "release": s + WIND,
                    "tx": rng.uniform(-0.7, 0.7), "ty": rng.uniform(0.3, 1.5),
                    "spd": rng.uniform(70, 95)})


def world(t):
    cur = None
    for p in pitches:
        if p["start"] <= t < p["start"] + CYCLE:
            cur = p
    if cur is None:
        return (0, 1.8, 18.0), (0, 1, 0, 0, 0)
    tt = t - cur["start"]
    tgt = (cur["tx"], cur["ty"])
    if tt < WIND:                                   # ball in the pitcher's hand, arm animating
        hand = (0.3 * np.sin(tt * 4), 1.8 + 0.4 * np.sin(tt * 3), 18.0 - 0.2 * np.sin(tt * 2))
        mitt = (tgt[0] * min(1, tt / WIND), 1 + (tgt[1] - 1) * min(1, tt / WIND))
        return hand, (*tgt, *mitt, cur["spd"])
    ft = tt - WIND
    if ft < 0.45:                                    # straight to the plate
        a = ft / 0.45
        pos = (0 + (tgt[0] - 0) * a, 1.8 + (tgt[1] - 1.8) * a, 18.0 * (1 - a))
    else:
        pos = (tgt[0], tgt[1], 0.0)
    return pos, (*tgt, *tgt, cur["spd"])


lp = c.LaunchPredictor()
dt = 1 / 15
t = 0.0
marks = {round(p["release"] + rng.uniform(-0.08, 0.1), 3): p for p in pitches}
done = set()
start = time.time()
preds = []
while t < pitches[-1]["start"] + CYCLE:
    fv[anim] += rng.normal(0, 0.3, len(anim)).astype("<f4")
    fv[osc] = (5 * np.sin(2 * np.pi * t / osc_p + osc_ph)).astype("<f4")
    pos, (tx, ty, mx, my, spd) = world(t)
    fv[BALL:BALL + 3] = pos
    fv[TGT:TGT + 2] = (tx, ty); fv[MITT:MITT + 2] = (mx, my); fv[SPEEDPICK] = spd
    for m, p in marks.items():
        if t >= m and m not in done:
            lp.mark(t); done.add(m)
    lp.feed(t, mem)
    # live prediction half way through each wind-up (what the overlay would show)
    for p in pitches:
        if lp.phase == "ready" and abs(t - (p["start"] + 0.9)) < dt / 2:
            pr = lp.predict(lambda a, vt: float(fv[a // 4]))
            preds.append((pr, p["tx"], p["ty"]))
    t += dt
print("\n".join(lp.log))
print(f"elapsed {time.time() - start:.1f}s, phase={lp.phase}, ball={lp.ball}, axes={lp.axis_cols}")
for ax, p in lp.predictors.items():
    print(ax, f"idx={p['idx']} addr={p['idx'] * 4:08X} r={p['r']:.3f} early={p['early']}")
assert lp.ball == BALL + 2, lp.ball
assert lp.phase == "ready"
assert lp.predictors["h"]["idx"] in (TGT, MITT) and lp.predictors["v"]["idx"] in (TGT + 1, MITT + 1)
assert lp.predictors["h"]["early"] and lp.predictors["h"]["idx"] == TGT   # the target is known earliest
print("mid-wind-up predictions vs real target:")
for pr, tx, ty in preds:
    print(f"  predicted ({pr['h']:+.2f}, {pr['v']:.2f})  actual ({tx:+.2f}, {ty:.2f})")
    assert abs(pr["h"] - tx) < 0.05 and abs(pr["v"] - ty) < 0.05
assert len(preds) >= 3
print("accuracy:", lp.accuracy_report())
print("PREDICT TESTS PASSED")
