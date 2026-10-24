import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import menubuilder as mb
import ps2core as core


def plan(text):
    items = mb.plan_from_text(text)
    for it in items:
        print(f"  {text[:30]:30} -> {mb.describe_item(it)}  | {it['group']} / {it['kind']}")
    return items


a = plan("infinite ammo on L1 and R1, god mode and super speed")
assert [i["find"] for i in a] == ["ammo", "health", "run speed"]
assert a[0]["mode"] == "freeze" and a[0]["hotkey"] == ["L1", "R1"] and a[0]["group"] == "Weapons"
assert a[1]["name"] == "God mode" and a[1]["group"] == "Health"
assert a[2]["kind"] == "speed" and a[2]["mode"] == "scale" and a[2]["value"] == 3.0

b = plan("build me a mod menu with unlimited money, moon jump, spawn a tank, double car speed on F3")
assert [i["kind"] for i in b] == ["value", "jump", "spawn", "speed"]
assert b[0]["name"] == "Unlimited money" and b[2]["spawn_kind"] == "Vehicles" and b[2]["group"] == "Spawn Vehicles"
assert b[3]["find"] == "car speed" and b[3]["value"] == 2.0 and b[3]["hotkey"] == ["F3"]

c = plan("give me 99 lives; top speed x4; wanted level 0 with R3; money +10000 on L2+R2")
assert c[0]["find"] == "lives" and c[0]["mode"] == "freeze" and c[0]["value"] == 99
assert c[1]["kind"] == "topspeed" and c[1]["value"] == 4.0 and c[1]["find"] == "run speed"
assert c[2]["find"] == "wanted level" and c[2]["value"] == 0 and c[2]["hotkey"] == ["R3"]
assert c[3]["mode"] == "add" and c[3]["value"] == 10000 and c[3]["hotkey"] == ["L2", "R2"]
assert len(plan("infinite ammo, unlimited ammo")) == 1            # same value once
try:
    mb.plan_from_text(" , ,")
    raise AssertionError("empty plan should fail")
except ValueError:
    pass

# AI brain: its JSON is checked; a broken brain falls back to the built-in one
class FakeBrain:
    usable, name = True, "Claude"
    def __init__(self, reply): self.reply = reply
    def chat(self, system, user, **k):
        assert "mod menu" in system and "Game: Mercenaries 2" in user
        if isinstance(self.reply, Exception): raise self.reply
        return self.reply
good = FakeBrain("Sure!\n" + json.dumps({"items": [
    {"name": "Infinite C4", "find": "C4 count", "kind": "value", "mode": "freeze", "value": 9, "hotkey": ["L1", "Up"],
     "group": "Weapons"},
    {"name": "Fast heli", "find": "helicopter speed", "kind": "speed", "mode": "freeze", "value": None},
    {"find": ""}, {"name": "Tank", "find": "which vehicle id", "kind": "spawn"}]}))
items, src, note = mb.plan_menu("c4, fast heli, tank", good, "Mercenaries 2")
assert src == "Claude" and note == "" and [i["name"] for i in items] == ["Infinite C4", "Fast heli", "Tank"]
assert items[0]["hotkey"] == ["L1", "Up"] and items[0]["value"] == 9
assert items[1]["mode"] == "scale" and items[1]["value"] == 3.0
assert items[2]["mode"] == "set" and items[2]["spawn_kind"] == "Vehicles"
items, src, note = mb.plan_menu("infinite ammo", FakeBrain(RuntimeError("HTTP 401")), "Mercenaries 2")
assert src == "built-in" and "401" in note and items[0]["find"] == "ammo"
items, src, _ = mb.plan_menu("infinite ammo", FakeBrain("no json here"), "Mercenaries 2")
assert src == "built-in"

# walking the items
lib = [core.new_value_entry("Ammo", "Weapons", 0x1000, "u16"), core.new_value_entry("Ammo? 1 (u32)", "Unsorted", 8, "u32"),
       core.new_value_entry("Run speed", "Running", 0x2000, "float")]
ammo, health, speed = a
assert mb.find_in_library(ammo, lib)["name"] == "Ammo"
assert mb.find_in_library(health, lib) is None
assert mb.find_in_library(speed, lib)["name"] == "Run speed"
assert mb.find_in_library(c[1], lib) is None                       # top speed needs its own setting
ch = mb.cheat_for(dict(ammo, value=99.6, mode="set"), lib[0])
assert ch["value"] == 100 and ch["entry"] == "Ammo" and ch["hotkey"] == ["L1", "R1"]
assert mb.cheat_for(speed, lib[2])["value"] == 3.0
core.cheat_writes(ch, lib)                                         # a real, usable cheat
bld = mb.MenuBuild(a)
assert bld.current["find"] == "ammo" and bld.progress() == "1/3"
bld.found("had"); bld.skip("no"); bld.found()
assert bld.done and bld.current is None
print(bld.summary())
assert bld.summary() == "Mod menu built: 2 cheat(s) (Infinite ammo, Super speed). Skipped: God mode."
print("MENU BUILDER TESTS PASSED")
