import sys, struct
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import numpy as np
import ps2core as c
rng = np.random.default_rng(5)

# ---------- MultiScanner: health is a byte in one game, float in another --------------
mem = np.zeros(c.EE_SIZE, np.uint8)
mem[rng.integers(0, c.EE_SIZE, 2_000_000)] = rng.integers(0, 256, 2_000_000, dtype=np.uint8)
HB, HF = 0x123457, 0x200000
mem[HB] = 100; mem[HF:HF + 4] = np.frombuffer(struct.pack("<f", 100.0), np.uint8)
ms = c.MultiScanner()
ms.first(mem.copy(), "all", "unknown")
noise = rng.choice(c.EE_SIZE, 300000, replace=False)
last = 100
for hp in (80, 55, 70, 30):
    s = mem.copy()
    s[noise] = rng.integers(0, 256, len(noise), dtype=np.uint8)
    s[HB] = hp; s[HF:HF + 4] = np.frombuffer(struct.pack("<f", float(hp)), np.uint8)
    ms.next(s, "decreased" if hp < last else "increased"); last = hp
    s2 = s.copy(); ms.next(s2, "unchanged")
    mem = s
got = {(a, vt) for a, vt, _, _ in ms.results_typed(mem, 500)}
print("multi counts:", ms.counts(), "found byte:", (HB, "byte") in got, "found float:", (HF, "float") in got)
assert (HB, "byte") in got and (HF, "float") in got
ms.first(mem, "all", "exact", 30)
got = {(a, vt) for a, vt, _, _ in ms.results_typed(mem, 100000)}
assert (HB, "byte") in got and (HF, "float") in got

# ---------- recorder events: shoot, shoot, reload ----------------------------------------
t = np.arange(0, 24, 1 / 60)
ammo = np.full(len(t), 30.0); used = np.zeros(len(t)); hp = np.full(len(t), 100.0)
clock = t * 1.0; jitter = rng.normal(0, 1, len(t)).cumsum()
marks, a, u = [], 30, 0
for i, m in enumerate(np.arange(2, 22, 2.0)):
    step = ["s", "s", "r"][i % 3]
    exp = -1 if step == "s" else +1
    marks.append((m + rng.uniform(-0.05, 0.08), exp))
    if step == "s":
        a -= 1; u += 1
    else:
        a = 30
    ammo[t >= m] = a; used[t >= m] = u
res = c.analyze_events(t, {"ammo": ammo, "used": used, "hp": hp, "clock": clock, "noise": jitter}, marks)
print([(r["key"], r["kind"], r["score"]) for r in res])
assert res[0]["key"] == "ammo" and res[0]["kind"] == "counter"
# jump bump
h = np.zeros(len(t)); jm = []
for m in np.arange(2, 20, 3.0):
    seg = (t >= m) & (t <= m + 0.8)
    h[seg] = 4 * (t[seg] - m) * (0.8 - (t[seg] - m)) * 5
    jm.append((m, "bump"))
res = c.analyze_events(t, {"height": h, "noise": jitter, "ammo": ammo}, jm)
assert res[0]["key"] == "height" and res[0]["kind"] == "bump", res

# ---------- moving struct: fingerprint + pointer paths ------------------------------------
class T:          # minimal target over a numpy buffer (PS2 style)
    profile, regions, ptr_size = "ps2", None, 4
    def __init__(self, m): self.m = m
    def read(self, a, vt):
        return c.decode(vt, self.m[a:a + c.TYPES[vt][2]].tobytes())
def launch(struct_at, seed):
    r = np.random.default_rng(seed)
    m = np.zeros(c.EE_SIZE, np.uint8)
    m[r.integers(0, c.EE_SIZE, 1_000_000)] = r.integers(0, 256, 1_000_000, dtype=np.uint8)
    # player struct: [id=0x1234][flags][max hp float 150][hp float][name "RAMBO"]...
    blob = struct.pack("<IIff", 0x1234, 0xA5A5, 150.0, 120.0) + b"RAMBO\0\0\0" + bytes(range(40, 104))
    m[struct_at:struct_at + len(blob)] = np.frombuffer(blob, np.uint8)
    # static pointer at 0x00300100 -> struct (the game's "player" global)
    m[0x300100:0x300104] = np.frombuffer(struct.pack("<I", struct_at), np.uint8)
    # a heap pointer that also points there this time only
    m[struct_at + 0x5000:struct_at + 0x5004] = np.frombuffer(struct.pack("<I", struct_at), np.uint8)
    return m
A1, A2 = 0x01A00040, 0x01B37280
m1 = launch(A1, 1)
snaps = [m1.copy(), m1.copy()]
snaps[1][A1 + 12:A1 + 16] = np.frombuffer(struct.pack("<f", 95.0), np.uint8)   # hp changed meanwhile
entry = c.new_value_entry("Health", "Health", A1 + 12, "float")
entry["fp"] = c.fingerprint(snaps, A1 + 12, "float")
t1 = T(m1)
entry["paths"] = c.pointer_scan(t1, m1, A1 + 12)
print("paths:", [(f"{b:08X}", p) for b, p in entry["paths"][:6]], len(entry["paths"]))
assert any(b == 0x300100 and p == [12] for b, p in entry["paths"])
# next launch: the struct moved
m2 = launch(A2, 2)
off, how = c.relocate(T(m2), m2, entry)
print("relocated:", f"{off:08X}" if off is not None else None, how)
assert off == A2 + 12
n = c.prune_paths(T(m2), entry, off)
assert any(b == 0x300100 for b, _ in entry["paths"]) and n < 6, entry["paths"]
# third launch, fingerprint damaged (name changed) -> pointer path still finds it
m3 = launch(0x01C00000, 3); m3[0x01C00000 + 16:0x01C00000 + 40] = 0
off, how = c.relocate(T(m3), m3, entry)
print("relocated 3:", f"{off:08X}", how)
assert off == 0x01C00000 + 12
print("MOVING / MULTI / EVENTS TESTS PASSED")
