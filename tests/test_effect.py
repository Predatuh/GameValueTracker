import sys, struct, threading, time
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import numpy as np
import ps2core as c

MEM = np.zeros(c.EE_SIZE, dtype=np.uint8)
LOCK = threading.Lock()


def read(a, vt):
    with LOCK:
        return c.decode(vt, MEM[a:a + c.TYPES[vt][2]].tobytes())


def write(a, vt, v):
    raw = c.encode(vt, v)
    with LOCK:
        MEM[a:a + len(raw)] = np.frombuffer(raw, dtype=np.uint8)
    return True


POS, VEL = 0x00C00000, 0x00C0000C        # real ball state (game physics uses these)
VCOPY = 0x00D00010                       # render copy of velocity, rewritten every frame
AMMO, HUD = 0x00456780, 0x00456980       # real ammo (u32) and HUD copy (u16)
state = {"run": True, "launch": 0}


def game():
    """60 fps game loop: reads its state from memory, so writes to the REAL values matter."""
    dt = 1 / 60
    write(AMMO, "u32", 40)
    while state["run"]:
        if state["launch"]:
            write(POS, "float", 0.0); write(POS + 4, "float", 1.0); write(POS + 8, "float", 0.0)
            write(VEL, "float", 3.0); write(VEL + 4, "float", 12.0); write(VEL + 8, "float", 30.0)
            state["launch"] = 0
        p = [read(POS + 4 * i, "float") for i in range(3)]
        v = [read(VEL + 4 * i, "float") for i in range(3)]
        if p[1] > 0:
            v[1] -= 9.8 * dt
            p = [p[i] + v[i] * dt for i in range(3)]
        else:
            v = [0.0, 0.0, 0.0]
        for i in range(3):
            write(POS + 4 * i, "float", p[i]); write(VEL + 4 * i, "float", v[i])
            write(VCOPY + 4 * i, "float", v[i])          # copy derived from the real value
        write(HUD, "u16", read(AMMO, "u32"))             # HUD redrawn from real ammo
        time.sleep(dt)


th = threading.Thread(target=game, daemon=True)
th.start()
time.sleep(0.2)
pos_watch = [(POS, "float"), (POS + 4, "float"), (POS + 8, "float")]

# --- ball: test the real forward velocity during flight -----------------------
state["launch"] = 1; time.sleep(0.15)
r_real = c.effect_test(read, write, (VEL + 8, "float"), [(VCOPY + 8, "float")], pos_watch,
                       mode="scale", factor=3, base_secs=0.25, test_secs=0.5)
print("real vz:", r_real["verdict"], r_real["note"])
assert r_real["verdict"] == "controls", r_real

# --- ball: test the render copy during another flight --------------------------
time.sleep(2.5); state["launch"] = 1; time.sleep(0.15)
r_copy = c.effect_test(read, write, (VCOPY + 8, "float"), [(VEL + 8, "float")], pos_watch,
                       mode="scale", factor=3, base_secs=0.25, test_secs=0.5)
print("copy vz:", r_copy["verdict"], r_copy["note"])
assert r_copy["verdict"] == "copy", r_copy

# --- ball at rest: skipped (can't scale 0) ------------------------------------------
time.sleep(3.0)
r_rest = c.effect_test(read, write, (VEL + 8, "float"), [], pos_watch, mode="scale")
assert r_rest["verdict"] == "skipped", r_rest

# --- ammo: real vs HUD copy -----------------------------------------------------------
r_ammo = c.effect_test(read, write, (AMMO, "u32"), [(HUD, "u16")], mode="offset", delta=7,
                       base_secs=0.2, test_secs=0.4)
r_hud = c.effect_test(read, write, (HUD, "u16"), [(AMMO, "u32")], mode="offset", delta=7,
                      base_secs=0.2, test_secs=0.4)
print("ammo:", r_ammo["verdict"], r_ammo["note"], "| hud:", r_hud["verdict"])
assert r_ammo["verdict"] == "controls" and r_hud["verdict"] == "copy", (r_ammo, r_hud)
time.sleep(0.1)
assert read(AMMO, "u32") == 40, "restored after test"

ranked = c.rank_tests([r_real, r_copy, r_ammo, r_hud, r_rest])
print([(f"{r['addr']:08X}", r["verdict"], r["score"]) for r in ranked])
assert ranked[0]["verdict"] == "controls"
state["run"] = False
print("EFFECT TESTS PASSED")
