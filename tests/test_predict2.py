"""Predictor v2: CPU picks a ZONE NUMBER (byte inside a word) before the wind-up.
Half the pitches get HIT at the plate (ball reverses), the rest are caught. A ball/strike
count byte and a pitch counter are decoys. No float target exists until release."""
import sys, time, json
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import numpy as np
import ps2core as c

MODE = sys.argv[1] if len(sys.argv) > 1 else "zone"
rng = np.random.default_rng(31 if MODE == "zone" else 21)
NF = c.EE_SIZE // 4
mem = np.zeros(c.EE_SIZE, dtype=np.uint8)
mem[rng.integers(0, c.EE_SIZE, 1_500_000)] = rng.integers(0, 256, 1_500_000, dtype=np.uint8)
fv = mem.view("<f4"); uv = mem.view("<u4")
BALL = 3_000_000
STATE = 3_200_000          # u32 word: byte0 = pitch type, byte1 = ZONE (0-8), byte2 = count, byte3 = flags
COUNTER = 3_200_004
TGT = 3_100_000            # float target (coords mode only)
anim = rng.choice(NF, 120_000, replace=False)
anim = anim[(np.abs(anim - BALL) > 10) & (np.abs(anim - STATE) > 10) & (np.abs(anim - TGT) > 10)]
ZX = np.array([-0.5, 0.0, 0.5] * 3); ZY = np.repeat([1.3, 0.9, 0.5], 3)

CYCLE, WIND = 4.5, 1.8
pitches = []
for k in range(22):
    z = int(rng.integers(0, 9))
    tx, ty = (ZX[z] + rng.normal(0, 0.01), ZY[z] + rng.normal(0, 0.01)) if MODE == "zone" else \
             (rng.uniform(-0.7, 0.7), rng.uniform(0.3, 1.5))
    pitches.append({"start": 1.0 + k * CYCLE, "release": 1.0 + k * CYCLE + WIND, "zone": z,
                    "tx": tx, "ty": ty, "hit": bool(rng.random() < 0.5),
                    "type": int(rng.integers(0, 4)), "count": int(rng.integers(0, 4))})


def world(t):
    cur = next((p for p in pitches if p["start"] <= t < p["start"] + CYCLE), None)
    if cur is None:
        return (0, 1.8, 18.0), None
    tt = t - cur["start"]
    if tt < WIND:
        return (0.3 * np.sin(tt * 4), 1.8 + 0.4 * np.sin(tt * 3), 18.0 - 0.2 * np.sin(tt * 2)), cur
    ft = tt - WIND
    if ft < 0.45:
        a = ft / 0.45
        return (cur["tx"] * a, 1.8 + (cur["ty"] - 1.8) * a, 18.0 * (1 - a)), cur
    if cur["hit"]:                       # batted ball goes back out
        b = ft - 0.45
        return (cur["tx"] + 3 * b, cur["ty"] + 8 * b - 4.9 * b * b, 30 * b), cur
    return (cur["tx"], cur["ty"], -0.3), cur   # caught a bit behind the plate


lp = c.LaunchPredictor()
dt = 1 / 15
t = 0.0
marks = sorted((round(p["release"] + rng.uniform(-0.08, 0.1), 3), i) for i, p in enumerate(pitches))
done, preds = set(), []
start = time.time()
while t < pitches[-1]["start"] + CYCLE:
    fv[anim] += rng.normal(0, 0.3, len(anim)).astype("<f4")
    pos, cur = world(t)
    fv[BALL:BALL + 3] = pos
    if cur:
        uv[STATE] = cur["type"] | (cur["zone"] << 8) | (cur["count"] << 16) | (0x40 << 24)
        uv[COUNTER] = pitches.index(cur)
        if MODE == "coords":
            fv[TGT:TGT + 2] = (cur["tx"], cur["ty"])
    for m, i in marks:
        if t >= m and m not in done:
            lp.mark(t); done.add(m)
    lp.feed(t, mem)
    for p in pitches:
        if lp.phase == "ready" and abs(t - (p["start"] + 0.9)) < dt / 2:
            preds.append((lp.predict(lambda a, vt: int(uv[a // 4]) if vt == "u32" else float(fv[a // 4])), p))
    t += dt
print("\n".join(lp.log[-8:]))
print(f"elapsed {time.time() - start:.1f}s phase={lp.phase} ball={lp.ball} plate={lp.plate}")
print("hits:", sum(p["hit"] for p in pitches), "measured:", len(lp.outcomes()))
print("candidates:", lp.candidates)
assert lp.ball == BALL + 2, lp.ball
assert lp.phase == "ready"
if MODE == "zone":
    assert lp.zone and lp.zone["addr"] == STATE * 4 and lp.zone["part"] == "b1", lp.zone
else:
    assert lp.predictors["h"]["idx"] == TGT and lp.predictors["v"]["idx"] == TGT + 1
good = 0
for pr, p in preds:
    if pr and "h" in pr:
        ok = abs(pr["h"] - p["tx"]) < 0.06 and abs(pr["v"] - p["ty"]) < 0.06
        print(f"  zone {p['zone']} hit={p['hit']}: predicted ({pr['h']:+.2f},{pr['v']:.2f}) actual ({p['tx']:+.2f},{p['ty']:.2f}) {'OK' if ok else 'MISS'}")
        assert ok
        good += 1
    else:
        print("  ", pr)
assert good >= 3
print("accuracy:", lp.accuracy_report())
json.dumps(lp.export(), default=str)
print(f"PREDICT V2 ({MODE}) PASSED")
