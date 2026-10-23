import sys, struct, json, io
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import numpy as np
import ps2core as core
import coach as C

# ---------------- brain: understanding requests ----------------------------------
cases = {
    "ammo i have 40 now": ("Weapons", "exact", 40),
    "my money, I have $1,250": ("Money", "exact", 1250),
    "health im full health": ("Health", "unknown", None),
    "health is 85": ("Health", "exact", 85),
    "car speed": ("pulse", "drive", None),
    "how fast my player runs": ("pulse", "run", None),
    "batting power / ball speed after i hit it": (None, None, None),   # event
    "how high i jump": ("pulse", "jump", None),
    "height of the cliff": ("Game State", "unknown", None),
    "game clock": ("Game State", "unknown", None),
    "wanted level": ("Game State", "exact", "ask"),
    "nitro boost": ("Vehicle", "unknown", None),
    "lap count 2": ("Other", "exact", 2),
    "the thing that makes my guy glow": ("Other", "unknown", None),
}
for text, (cat, first, val) in cases.items():
    r = C.plan_from_text(text)
    if cat == "pulse":
        assert r["mode"] == "pulse" and r["pulse"]["kind"] == first, (text, r)
        print(f"{text!r:45} -> PULSE ({first})")
        continue
    if cat is None:
        assert r["mode"] == "event", (text, r)
        print(f"{text!r:45} -> EVENT ({r['event']['action']})")
        continue
    f = next(s for s in r["steps"] + r["loop"] if s["scan"])
    assert r["category"] == cat, (text, r["category"])
    assert f["scan"] == first, (text, f)
    if val is not None:
        assert f.get("value") == val, (text, f)
    print(f"{text!r:45} -> {r['title']!r:22} {r['category']:10} first={f['scan']} types={r['types']}")

# ---------------- Claude path (mocked network) -------------------------------------
fake_reply = {"content": [{"type": "text", "text": "Here you go:\n" + json.dumps({
    "title": "Boost meter", "category": "Vehicle", "types": ["float"],
    "steps": [{"say": "Fill your boost", "scan": "unknown", "until": "timer", "secs": 3}],
    "loop": [{"say": "Use boost", "scan": "decreased", "until": "key"},
             {"say": "Wait", "scan": "unchanged", "secs": 2}], "target": 4, "max_loops": 5})}]}


class FakeResp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): pass


import brain as B
B.urllib.request.urlopen = lambda req, timeout=60: FakeResp(json.dumps(fake_reply).encode())
r, src, note = C.make_plan("the boost bar in burnout", api_key="sk-test")
assert src == "Claude" and r["title"] == "Boost meter" and r["loop"][0]["until"] == "key"
def boom(*a, **k): raise OSError("no network")
B.urllib.request.urlopen = boom
r, src, note = C.make_plan("car speed", api_key="sk-test")
assert src == "built-in" and "unavailable" in note
print("Claude planner OK (and falls back when offline)")
bad = {"steps": [{"say": "x", "scan": "increased"}], "loop": [{"say": "y", "scan": "decreased"}]}
v = C.validate_recipe(bad)
assert v["steps"][0]["scan"] == "unknown"   # compare-scan can't come first

# ---------------- simulated games --------------------------------------------------
rng = np.random.default_rng(11)


def new_world():
    mem = np.zeros(core.EE_SIZE, dtype=np.uint8)
    idx = rng.integers(0, core.EE_SIZE, 2_000_000)
    mem[idx] = rng.integers(0, 256, len(idx), dtype=np.uint8)
    return mem


def put(mem, addr, vt, v):
    raw = core.encode(vt, v)
    mem[addr:addr + len(raw)] = np.frombuffer(raw, dtype=np.uint8)


def tick(mem, f_noise, u_timers, t):
    """things in the game that move on their own"""
    fv = mem.view("<f4")
    fv[f_noise] += rng.normal(0, 0.3, len(f_noise)).astype("<f4")
    mem.view("<u4")[u_timers] = int(t * 60)


def run(recipe, game, mem, typed_values):
    """Play a recipe: `game(step_say, scan)` changes memory the way the player would."""
    co = C.Coach(recipe)
    f_noise = rng.choice(core.EE_SIZE // 4, 40_000, replace=False)
    u_timers = rng.choice(core.EE_SIZE // 4, 500, replace=False)
    t, steps = 0.0, 0
    while not co.done and steps < 60:
        s = co.current()
        typed = game(s, mem)
        t += max(1.0, s["secs"])
        tick(mem, f_noise, u_timers, t)
        co.apply(mem, typed if s.get("value") == "ask" else None)
        steps += 1
    return co, steps


# Game 1: GTA ammo, player says 40
mem = new_world()
AMMO = 0x00456780
for d in (0x00100000, 0x00200040, 0x00333330):
    put(mem, d, "u32", 40)                    # other things that happen to be 40
put(mem, AMMO, "u32", 40)
put(mem, AMMO + 0x200, "u16", 40)              # HUD copy as u16
state = {"ammo": 40}


def ammo_game(step, mem):
    if "shoot" in step["say"]:
        state["ammo"] -= 3
    elif "reload" in step["say"]:
        state["ammo"] += 10
    put(mem, AMMO, "u32", state["ammo"]); put(mem, AMMO + 0x200, "u16", state["ammo"])
    return state["ammo"]


co, n = run(C.plan_from_text("ammo i have 40 now"), ammo_game, mem, None)
res = co.results(mem)
print("ammo:", n, "steps ->", [(vt, f"{a:08X}") for vt, a, v in res])
assert co.done and not co.failed and ("u32", AMMO) in [(vt, a) for vt, a, v in res]

# Game 2: health is a float 0..100, full at start
mem = new_world()
HP = 0x00876540
put(mem, HP, "float", 100.0)
hp = {"v": 100.0}


def hp_game(step, mem):
    if "Lose" in step["say"]:
        hp["v"] -= rng.uniform(10, 25)
    elif "back" in step["say"]:
        hp["v"] = min(100.0, hp["v"] + 8)
    put(mem, HP, "float", hp["v"])


co, n = run(C.plan_from_text("health im full health"), hp_game, mem, None)
res = co.results(mem)
print("health:", n, "steps ->", [(vt, f"{a:08X}") for vt, a, v in res][:6], co.summary())
assert not co.failed and ("float", HP) in [(vt, a) for vt, a, v in res]

# Game 3: car speed float + an RPM value that moves with it (a fair second answer)
mem = new_world()
SPD, RPM = 0x00ABCDE0, 0x00ABCE40
spd = {"v": 0.0}


def car_game(step, mem):
    say = step["say"]
    if "Accelerate" in say:
        spd["v"] = rng.uniform(60, 120)
    elif "Brake" in say or "stopped" in say.lower():
        spd["v"] = 0.0
    put(mem, SPD, "float", spd["v"]); put(mem, RPM, "float", 800 + spd["v"] * 50)


# car speed is now a pulse hunt: floor it once, it rises and comes back
assert C.plan_from_text("car speed")["mode"] == "pulse"
ph = core.PulseHunter(2.2, 7.5)
for k in range(4):
    pre = mem.copy(); tick(mem, rng.choice(core.EE_SIZE // 4, 20000), [], k)
    put(mem, SPD, "float", rng.uniform(60, 120)); put(mem, RPM, "float", 800 + 90 * 50)
    mid = mem.copy()
    put(mem, SPD, "float", 0.0); put(mem, RPM, "float", 800.0)
    post = mem.copy()
    ph.add(pre, mid, post)
print("car speed pulse:", ph.log[-1], [(f"{a:08X}", vt) for a, vt in ph.candidates(6)])
assert (SPD, "float") in ph.candidates()
print("COACH TESTS PASSED")
