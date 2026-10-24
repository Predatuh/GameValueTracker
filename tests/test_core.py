import sys, struct
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import numpy as np
import ps2core as c

rng = np.random.default_rng(1)
EE = c.EE_SIZE

# ---- synthetic PS2 RAM with a roster table --------------------------------
mem = rng.integers(0, 256, EE, dtype=np.uint8)
BASE, STRIDE, N = 0x00A31240, 0x88, 120
OFFS = {"SPD": 0x10, "ACC": 0x11, "STR": 0x14, "KPW": 0x1C, "KAC": 0x1D, "AWR": 0x20}
truth = []
for i in range(N):
    rec = {k: int(rng.integers(40, 100)) for k in OFFS}
    # make values distinct inside a record
    while len(set(rec.values())) < len(rec):
        rec = {k: int(rng.integers(40, 100)) for k in OFFS}
    truth.append(rec)
    for k, off in OFFS.items():
        mem[BASE + i * STRIDE + off] = rec[k]
    # pad fields of the record with small values like real records
    for j in range(STRIDE):
        if j not in OFFS.values():
            mem[BASE + i * STRIDE + j] = rng.integers(0, 60)
# junk right before/after the table
mem[BASE - 4 * STRIDE:BASE] = 255
mem[BASE + N * STRIDE:BASE + (N + 4) * STRIDE] = 0

p1, p2 = 17, 63
f1 = c.parse_fields(", ".join(f"{k}={v}" for k, v in truth[p1].items()))
f2 = c.parse_fields("\n".join(f"{k}: {v}" for k, v in truth[p2].items()))

# --- edit method on very noisy memory ---
anchor = "SPD"
a1 = BASE + p1 * STRIDE + OFFS["SPD"]
before = mem.copy(); after = mem.copy(); after[a1] = (truth[p1]["SPD"] + 1) & 0xFF
hits = c.find_changed_bytes(before, after, truth[p1]["SPD"], truth[p1]["SPD"] + 1)
assert hits == [a1], hits
opts = c.locate_fields(mem, a1, f1, window=256)
print("ambiguous per label:", {k: len(v) for k, v in opts.items()})
a2 = BASE + p2 * STRIDE + OFFS["SPD"]
res = c.resolve_with_second(mem, a2, f2, opts)
print("after player 2:", {k: v for k, v in res.items()})
assert all(len(v) >= 1 and v[0] == OFFS[k] - OFFS["SPD"] for k, v in res.items())
offsets = {k: v[0] for k, v in res.items()}
best = {"anchor_a": a1, "anchor_b": a2, "offsets": offsets}

# --- auto method on realistic memory (mostly zeros + sparse noise) ---
real = np.zeros(EE, dtype=np.uint8)
noise_idx = rng.integers(0, EE, 400000)
real[noise_idx] = rng.integers(0, 256, len(noise_idx), dtype=np.uint8)
real[BASE - 64: BASE + (N + 2) * STRIDE] = mem[BASE - 64: BASE + (N + 2) * STRIDE]
real[BASE - 4 * STRIDE:BASE] = 255
auto = c.auto_match(real, f1, f2, window=256)
print("auto results:", len(auto))
assert auto and auto[0]["anchor_a"] == BASE + p1 * STRIDE + OFFS[auto[0]["anchor_label"]]
tab_auto = c.detect_table(real, auto[0]["anchor_a"], auto[0]["anchor_b"], auto[0]["offsets"])
print("auto table", tab_auto)
assert tab_auto["stride"] == STRIDE and tab_auto["count"] == N

tab = c.detect_table(mem, best["anchor_a"], best["anchor_b"], best["offsets"])
print("table", tab)
assert tab["stride"] == STRIDE and tab["count"] == N
assert tab["first_anchor"] == BASE + OFFS[anchor]

entry = c.new_table_entry("Roster", "Ratings", tab["first_anchor"], tab["stride"], tab["count"], best["offsets"])
assert c.table_field_addr(entry, 5, "KPW") == BASE + 5 * STRIDE + OFFS["KPW"]

# ---- scanner ---------------------------------------------------------------
snap = mem.copy()
ADDR = 0x00456780  # u32 aligned
struct.pack_into("<I", snap, ADDR, 30)
s = c.Scanner()
n0 = s.first(snap, "u32", "exact", 30)
snap2 = snap.copy(); struct.pack_into("<I", snap2, ADDR, 29)
s.next(snap2, "exact", 29)
assert ADDR in [a for a, _, _ in s.results(snap2)]
assert s.count <= n0
# unknown + decreased
s.first(snap2, "u32", "unknown")
snap3 = snap2.copy(); struct.pack_into("<I", snap3, ADDR, 20)
s.next(snap3, "decreased")
s.next(snap3, "unchanged")
assert ADDR in [a for a, _, _ in s.results(snap3, limit=10**6)]
assert s.count == 1, s.count
# float
FA = 0x00300000
fs = snap.copy(); struct.pack_into("<f", fs, FA, 7.5)
s.first(fs, "float", "exact", 7.5)
assert FA in [a for a, _, _ in s.results(fs, limit=10**6)]
# byte unknown -> changed
s.first(snap, "byte", "unknown")
b2 = snap.copy(); b2[0x1234] ^= 0xFF
s.next(b2, "changed")
assert s.count == 1 and s.results(b2)[0][0] == 0x1234

# ---- pnach -----------------------------------------------------------------
lib = [entry,
       c.new_value_entry("Kick meter", "Kicking", 0x0032A4C0, "u32"),
       c.new_value_entry("Pad buttons", "Controller", 0x003A0000, "u16"),
       c.new_value_entry("Speed f", "Running", 0x00100004, "float")]
assert c.pnach_line(0x0032A4C0, "u32", 9999) == "patch=1,EE,2032A4C0,extended,0000270F"
assert c.pnach_line(0x00100005, "byte", 99) == "patch=1,EE,00100005,extended,00000063"
assert c.pnach_line(0x00100004, "float", 1.0) == "patch=1,EE,20100004,extended,3F800000"
cheats = [
    {"name": "Max kick", "entry": "Kick meter", "value": 9999, "activator": None},
    {"name": "All 99 speed", "entry": "Roster", "field": "SPD", "record": "all", "value": 99,
     "activator": {"entry": "Pad buttons", "value": 0xFEFF}},
]
text = c.build_pnach("NCAA Football 2006", cheats, lib)
lines = text.splitlines()
assert lines[0] == "gametitle=NCAA Football 2006"
assert "[All 99 speed]" in lines
econds = [l for l in lines if ",E0" in l]
assert econds[0] == "patch=1,EE,E078FEFF,extended,003A0000", econds[0]  # 120 = 0x78 lines
print(text[:400])
print("ALL TESTS PASSED")

# ---- copies / mirrors ------------------------------------------------------
m2 = mem.copy()
table_bytes = m2[BASE:BASE + N * STRIDE].copy()
COPY = 0x01200000
m2[COPY:COPY + N * STRIDE] = table_bytes                    # full roster copy
BUF = 0x01800040
m2[BUF:BUF + STRIDE] = m2[BASE + 7 * STRIDE: BASE + 8 * STRIDE]  # edit buffer for player 7
ent = c.new_table_entry("R", "Ratings", BASE + OFFS["SPD"], STRIDE, N,
                        {k: v - OFFS["SPD"] for k, v in OFFS.items()})
cp = c.find_copies(m2, ent, 7)
print("copies:", cp)
kinds = sorted((x["record"] is None) for x in cp)
assert kinds == [False, True], cp
ent["mirrors"] = [{"delta": x["delta"], "record": x["record"]} for x in cp]
a7 = c.table_write_addrs(ent, 7, "SPD")
a8 = c.table_write_addrs(ent, 8, "SPD")
assert len(a7) == 3 and len(a8) == 2, (a7, a8)
assert BASE + 7 * STRIDE + OFFS["SPD"] in a7 and COPY + 7 * STRIDE + OFFS["SPD"] in a7
assert BUF + OFFS["SPD"] in a7
lines = c.cheat_lines({"name": "x", "entry": "R", "field": "SPD", "record": 7, "value": 99}, [ent])
assert len(lines) == 3

# pointers (addresses the game follows) are never poked by the tests - that crashes games
class _PT:
    profile = "ps3"
    regions = [c.Region(0, 0x300000000, 0x10000000, 0, "main"), c.Region(0x10000000, 0x330000000, 0x1000000, 0x30000000, "")]
assert c.looks_like_pointer(_PT, 0x30001230, "u32") and c.looks_like_pointer(_PT, 0x00456780, "u32")
assert not c.looks_like_pointer(_PT, 100, "u32") and not c.looks_like_pointer(_PT, 0x30001231, "u32")
assert not c.looks_like_pointer(_PT, 0x30001230, "u16") and not c.looks_like_pointer(_PT, 0x7FFF0000, "u32")
_PT.profile = "pc"
assert not c.looks_like_pointer(_PT, 0x30001230, "u32")
print("COPY TESTS PASSED")
