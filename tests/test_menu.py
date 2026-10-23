import sys; sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import modmenu as m
names = ["Ammo", "Money", "Health", "Wanted level", "Car speed"]
for text in ["infinite ammo on L1+R1", "money +10000 when I press L2 + R2", "double car speed",
             "health 999", "set wanted level to 0 with F3", "unlimited health", "give me 5000 money on numpad 7"]:
    c = m.describe_cheat(text, names)
    print(f"{text!r:45} -> {c['entry']:12} {c['mode']:8} {c['value']} {c['hotkey']} | {c['name']}")
c1 = m.describe_cheat("infinite ammo on L1+R1", names); assert c1["entry"] == "Ammo" and c1["mode"] == "freeze" and c1["hotkey"] == ["L1", "R1"]
c2 = m.describe_cheat("money +10000 when I press L2 + R2", names); assert c2["mode"] == "add" and c2["value"] == 10000 and c2["hotkey"] == ["L2", "R2"]
c3 = m.describe_cheat("double car speed", names); assert c3["entry"] == "Car speed" and c3["mode"] == "scale" and c3["value"] == 2
c4 = m.describe_cheat("set wanted level to 0 with F3", names); assert c4["entry"] == "Wanted level" and c4["mode"] == "set" and c4["value"] == 0 and c4["hotkey"] == ["F3"]
assert m.parse_combo("L3 + R1") == ["L3", "R1"] and m.parse_combo("numpad 5") == ["Num5"]

# engine
cheats = [dict(c1), dict(c2), {"name": "Tank", "entry": "Veh", "mode": "set", "value": 432, "group": "Spawn: Vehicles"}]
e = m.MenuEngine(cheats)
def press(*b): return e.tick(set(b))
assert press("L1", "R1") == [("toggle", cheats[0])] and cheats[0]["on"]          # direct hotkey
press()
assert press("L3", "R1") == [("menu", True)] and e.open
assert e.rows()[0][0].startswith("Cheats")
press(); press("Down"); press(); assert e.cursor == 1
press("Cross"); assert e.group == "Spawn: Vehicles"
press(); ev = press("Cross"); assert ev == [("fire", cheats[2])], ev
press(); press("Circle"); assert e.group is None and e.open
press(); press("Circle"); assert not e.open
press(); assert press("Insert") == [("menu", True)]
assert [c["name"] for c in e.frozen()] == [cheats[0]["name"]]
assert m.apply_value("add", 50, 10) == 60 and m.apply_value("multiply", 3, 2) == 6
mp = m.learn_pad_mapping(0xFFFF, {"L1": 0xFBFF, "R1": 0xF7FF, "Cross": 0xBFFF})
assert m.mem_pad_pressed(0xF3FF, mp) == {"L1", "R1"}
print("MENU TESTS PASSED")
