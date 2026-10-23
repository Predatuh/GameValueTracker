import sys, time
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import numpy as np
import ps2core as c

rng = np.random.default_rng(7)
NF = 2_000_000                       # floats in our fake RAM (8 MB)
mem = np.zeros(NF, dtype="<f4")
static = rng.normal(0, 50, NF).astype("<f4")
mem[:] = static
anim = rng.choice(NF, 150_000, replace=False)          # random walkers (animations)
osc = rng.choice(np.setdiff1d(np.arange(NF), anim), 60_000, replace=False)  # oscillators (flip sign)
osc_per = rng.uniform(0.4, 3.0, len(osc)); osc_ph = rng.uniform(0, 6.28, len(osc))
timers = rng.choice(NF, 2000, replace=False)
BALL = 1_234_560                      # pos x,y,z vel x,y,z  (float index)
BAT = 1_500_002                       # bat angle: flips sign at every swing (decoy)
for i in range(BALL - 8, BALL + 14):
    mem[i] = 0.0
anim = anim[(np.abs(anim - BALL) > 20) & (anim != BAT)]
osc_m = (np.abs(osc - BALL) > 20) & (osc != BAT)
osc, osc_per, osc_ph = osc[osc_m], osc_per[osc_m], osc_ph[osc_m]

plays = [3.0 + 7.0 * k + rng.uniform(-1, 1) for k in range(8)]   # contact times


def ball_state(t):
    pos = np.array([0.0, 1.5, 18.0]); vel = np.zeros(3); bat = -0.8
    for p in plays:
        if p - 0.6 <= t < p:                     # pitch toward plate
            tt = t - (p - 0.6)
            vel = np.array([0.0, -0.3, -30.0]); pos = np.array([0.0, 1.5 - 0.3 * tt, 18 - 30 * tt])
        if p - 0.15 <= t < p + 0.35:             # bat swing: -0.8 -> +0.8
            bat = -0.8 + 1.6 * min(1, (t - (p - 0.15)) / 0.3)
        if p <= t < p + 6.0:
            tt = t - p
            v0 = np.array([rng_play[p][0], rng_play[p][1], rng_play[p][2]])
            flight = 2 * v0[1] / 9.8
            if tt < flight:
                vel = np.array([v0[0], v0[1] - 9.8 * tt, v0[2]])
                pos = np.array([v0[0] * tt, 1.0 + v0[1] * tt - 4.9 * tt * tt, v0[2] * tt])
            else:
                pos = np.array([v0[0] * flight, 0.0, v0[2] * flight]); vel = np.zeros(3)
    return pos, vel, bat


rng_play = {p: (rng.uniform(-8, 8), rng.uniform(8, 16), rng.uniform(25, 40)) for p in plays}

hunter = c.AutoHunter()
dt = 1 / 15
t = 0.0
user_marks = {p: p + rng.uniform(-0.25, 0.3) for p in plays}    # sloppy tapping
done = set()
start = time.time()
while t < plays[-1] + 4:
    mem[anim] += rng.normal(0, 0.5, len(anim)).astype("<f4")
    mem[osc] = (10 * np.sin(2 * np.pi * t / osc_per + osc_ph)).astype("<f4")
    mem[timers] = t
    pos, vel, bat = ball_state(t)
    mem[BALL:BALL + 3] = pos; mem[BALL + 3:BALL + 6] = vel; mem[BAT] = bat
    for p, m in user_marks.items():
        if t >= m and p not in done:
            hunter.mark(t); done.add(p)
    hunter.feed(t, mem.view(np.uint8))
    t += dt
hunter.analyze()
print("\n".join(hunter.log))
print(f"elapsed {time.time() - start:.1f}s")
for r in hunter.results[:8]:
    print(f"{r['addr']:08X} idx={r['addr'] // 4:>8} {r['kind']:7s} {r['score']:.3f} flips {r['flips']}/{r['hits']}")
best_speed = hunter.best("speed")
best_v = hunter.best("vspeed")
best_h = hunter.best("height")
print("speed", best_speed and best_speed["addr"] // 4, "vspeed", best_v and best_v["addr"] // 4,
      "height", best_h and best_h["addr"] // 4)
assert best_speed and best_speed["addr"] // 4 in (BALL + 5, BALL + 3), best_speed
assert best_v and best_v["addr"] // 4 == BALL + 4, best_v
assert hunter.results[0]["addr"] // 4 in range(BALL, BALL + 6), hunter.results[0]
assert all(r["addr"] // 4 != BAT or r["score"] < hunter.results[0]["score"] for r in hunter.results)

# auto hit detection from the ball's forward position
hd = c.HitDetector()
tt, found = 0.0, []
while tt < plays[3]:
    pos, vel, bat = ball_state(tt)
    if hd.step(tt, float(pos[2])):
        found.append(round(tt, 2))
    tt += 1 / 60
print("auto-detected hits:", found, "true:", [round(p, 2) for p in plays[:4]])
for f_, p in zip(found, plays[:4]):
    assert abs(f_ - p) < 0.1, (found, plays[:4])
hd2 = c.HitDetector(); tt, f2 = 0.0, []
while tt < plays[3]:
    if hd2.step(tt, float(ball_state(tt)[1][2])): f2.append(round(tt, 2))
    tt += 1 / 60
print("from velocity:", f2)
for f_, p in zip(f2, plays[:4]):
    assert abs(f_ - p) < 0.1
print("HUNT TESTS PASSED")
