import sys, threading, time
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import numpy as np
import ps2core as c

rng = np.random.default_rng(13)
MEM = np.zeros(c.EE_SIZE, dtype=np.uint8)
FV = MEM.view("<f4")
LOCK = threading.RLock()


def read(a, vt):
    with LOCK:
        return c.decode(vt, MEM[a:a + c.TYPES[vt][2]].tobytes())


def write(a, vt, v):
    raw = c.encode(vt, v)
    with LOCK:
        MEM[a:a + len(raw)] = np.frombuffer(raw, dtype=np.uint8)
    return True


POS, VEL = 2_000_000, 2_000_003          # ball position / velocity (velocity REBUILT every frame)
POWER, DIR = 2_100_000, 2_100_004        # hit power (set at contact) + direction unit vector
decoys = rng.choice(np.arange(500_000, 1_500_000), 3000, replace=False)
FV[decoys] = rng.uniform(1, 100, len(decoys)).astype("<f4")
G = {"run": True, "launch": False}


def game():
    dt = 1 / 60
    while G["run"]:
        with LOCK:
            if G["launch"]:
                FV[POS:POS + 3] = (0, 1, 0)
                d = np.array([rng.uniform(-.2, .2), 0.35, 1.0]); d /= np.linalg.norm(d)
                FV[DIR:DIR + 3] = d
                FV[POWER] = rng.uniform(30, 40)
                FV[2_000_010] = 0.0                     # flight time
                G["launch"] = False
            p = FV[POS:POS + 3].astype(float)
            if p[1] > 0:
                ft = FV[2_000_010] + dt
                FV[2_000_010] = ft
                v = FV[DIR:DIR + 3].astype(float) * FV[POWER]   # velocity rebuilt from POWER
                v[1] -= 9.8 * ft
                FV[VEL:VEL + 3] = v
                FV[POS:POS + 3] = p + v * dt
            else:
                FV[VEL:VEL + 3] = 0
            FV[decoys[:50]] += 0.001                    # a few decoys drift on their own
        time.sleep(dt)


threading.Thread(target=game, daemon=True).start()
time.sleep(0.2)

# --- the quick per-value test can't fix this game: velocity is rewritten every frame ---
G["launch"] = True; time.sleep(0.2)
r = c.effect_test(read, write, (VEL * 4 + 8, "float"), [], [(POS * 4 + 8, "float")], factor=3,
                  base_secs=0.12, test_secs=0.35)
print("quick test on velocity:", r["verdict"])
assert r["verdict"] == "copy"

# --- deep test over 3001 values (power hidden at a random position) ---
pool = list(decoys)
pool.insert(int(rng.integers(0, len(pool))), POWER)
gt = c.GroupTester([int(i) * 4 for i in pool], group_size=512)
watchers = [POS * 4 + 4, POS * 4 + 8]
launches = 0
start = time.time()
while not gt.done and launches < 40:
    time.sleep(1.6)
    G["launch"] = True; launches += 1
    time.sleep(0.2)
    for _ in range(2):                                  # two tests per flight
        g = gt.next_group()
        if g is None:
            break
        res = c.group_effect_test(read, write, g, watchers, factor=3.0)
        gt.record(g, res)
print("\n".join(gt.log[-6:]))
print(f"launches used: {launches}, tests: {gt.tests}, found: {[(f'{a:08X}', r) for a, r in gt.found]}, "
      f"{time.time() - start:.0f}s")
assert gt.found and gt.found[0][0] == POWER * 4
assert all(a == POWER * 4 for a, _ in gt.found)
G["run"] = False
print("DEEP TESTS PASSED")
