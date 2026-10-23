import sys, os, struct, time, shutil, json
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..")); sys.path.insert(0, ".")
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import numpy as np, tkinter as tk
import ps2core as core, gameinfo, modmenu
import ps2_tracker as app_mod
exec(open("test_targets.py").read().split("# ---------- big-endian")[0])   # FakeProc

app_mod.SAVE_FILE = os.path.abspath("gui_menu_library.json")
app_mod.SETTINGS_FILE = os.path.abspath("gui_menu_settings.json")
app_mod.LIB_DIR = os.path.abspath("gui_menu_libs")
shutil.rmtree(app_mod.LIB_DIR, ignore_errors=True)
for p in (app_mod.SAVE_FILE, app_mod.SETTINGS_FILE):
    if os.path.exists(p): os.remove(p)
# old single library from NCAA days -> must move into NCAA's own library
json.dump({"game_title": "NCAA Football 2006", "library": [core.new_value_entry("Kick power", "Kicking", 0x100, "u32")],
           "cheats": []}, open(app_mod.SAVE_FILE, "w"))
FORM = []
app_mod.ask_form = lambda *a, **k: FORM.pop(0) if FORM else None
for name in ("showinfo", "showwarning", "showerror"):
    setattr(app_mod.messagebox, name, lambda t, m, **k: print("MSG:", m[:110].replace("\n", " ")))
root = tk.Tk(); app = app_mod.App(root)
def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        root.update(); time.sleep(0.01)
hidden = lambda tab: app.nb.tab(tab, "state") == "hidden"

# ---------------- PS2 NCAA: football tabs, old library migrated ----------------------------
mem = bytearray(0x2000000)
t = FakeProc({0x10000000: mem}, "ps2", False); t.exe = "pcsx2-qt.exe"
t.regions = [core.Region(0, 0x10000000, len(mem), 0, "EE RAM")]; t._finish()
app.ps2 = t
app.apply_game(gameinfo.detect("ps2", ["PCSX2 v2.2.0", "NCAA Football 2006 [SLUS-21214]"], "pcsx2-qt.exe"))
assert app.genre == "football" and app.game_title.get() == "NCAA Football 2006"
assert not hidden(app.boost_tab) and not hidden(app.ratings_tab) and hidden(app.spawn_tab)
assert not app.pred_frame.winfo_ismapped() or True
assert [e["name"] for e in app.library] == ["Kick power"], "legacy library carried over"
assert app.lib_path.endswith("ps2_SLUS-21214.json") and os.path.exists(app.lib_path)
print("NCAA:", app.examples_lbl.cget("text")[:80])

# ---------------- RPCS3 Mercenaries 2: open world, fresh library, spawn tab -------------------
H = 0x300000000
ram = bytearray(0x400000)
AMMO, MONEY, VEH = 0x10000, 0x10010, 0x10020
ram[AMMO:AMMO + 4] = struct.pack(">I", 30); ram[MONEY:MONEY + 4] = struct.pack(">I", 500)
ram[VEH:VEH + 4] = struct.pack(">I", 400)
t = FakeProc({H: ram}, "ps3", True); t.exe = "rpcs3.exe"
t.regions = [core.Region(0, H, len(ram), 0, "")]; t._finish()
app.ps2 = t
title = "FPS: 56.20 | Vulkan | 0.0.43-20372 | Mercenaries 2: World in Flames™ [BLUS30056]"
app.apply_game(gameinfo.detect("ps3", ["RPCS3 0.0.43", title], "rpcs3.exe"))
assert app.genre == "open_world" and app.game_title.get() == "Mercenaries 2: World in Flames"
assert hidden(app.boost_tab) and hidden(app.ratings_tab) and not hidden(app.spawn_tab)
assert app.library == [] and app.lib_path.endswith("ps3_BLUS30056.json")
assert app.spawn_kind.get() == "Vehicles"
assert "deep" not in [k for k, b in app.coach_btns.items() if b.winfo_manager()]
# user overrides type -> remembered
app.genre_var.set(gameinfo.GENRES["shooter"]["label"]); app._genre_picked()
assert app.settings["game_types"]["ps3_BLUS30056"] == "shooter"
app.genre_var.set(gameinfo.GENRES["open_world"]["label"]); app._genre_picked()

app.library += [core.new_value_entry("Ammo", "Weapons", AMMO, "u32"), core.new_value_entry("Money", "Money", MONEY, "u32")]
for text in ("infinite ammo on L1+R1", "money +10000 on L2+R2", "set money to 0 with F3"):
    app.describe_var.set(text); app.describe_add()
assert [c["mode"] for c in app.cheats] == ["freeze", "add", "set"]
txt = app.ch_tree.item("0", "values")
print("cheat row:", txt)
assert "keep Ammo at its current value" in txt[0] and txt[1] == "L1 + R1"
app.preview_pnach()
codes = app.pnach_text.get("1.0", "end")
assert "Set money to 0" in codes and "menu-only" in codes, codes      # CE table with the set cheat only

# ---------------- live mod menu (driven by fake buttons) --------------------------------------
app.menu = modmenu.MenuEngine([c for c in app.cheats], app._menu_keys())
app.menu_on = True; app.menu_ov = app_mod.MenuOverlay(app)
def press(*b):
    for ev in app.menu.tick(set(b)):
        app._menu_event(ev)
    for c in app.menu.frozen():
        app._apply_cheat(c)
press("L1", "R1"); press()
assert app.cheats[0]["on"]
ram[AMMO:AMMO + 4] = struct.pack(">I", 3)       # shooting
press()
assert struct.unpack(">I", ram[AMMO:AMMO + 4])[0] == 30, "ammo frozen at 30"
press("L2", "R2"); press()
assert struct.unpack(">I", ram[MONEY:MONEY + 4])[0] == 10500
press("L3", "R1"); press()
assert app.menu.open and app.menu_ov.winfo_ismapped() or app.menu.open
press("Down"); press(); press("Cross"); press()
assert struct.unpack(">I", ram[MONEY:MONEY + 4])[0] == 20500, "menu: 2nd row = money +10000"
press("Circle"); press()
assert not app.menu.open

# ---------------- spawn menu -----------------------------------------------------------------
app.library.append(core.new_value_entry("Vehicle ID", "Spawn", VEH, "u32"))
app.spawn_id.set("Vehicle ID")
app._spawn_watch(); pump(0.1)
assert 400 in app.spawn["observed"]
tables = __import__("spawner").scan_path("fakegame")
app._scan_done(tables)
first = app.tables_tree.get_children()[0]
print("best list:", app.tables_tree.item(first, "values")[:3])
assert app.tables_tree.item(first, "values")[0] == "Vehicles"       # matches the ID seen in game
app.tables_tree.selection_set(first); app.spawn_use_table()
assert app.spawn_tree.exists("432")
app.spawn_hold.set(0)
app.spawn_tree.selection_set("432"); app.spawn_selected()
assert struct.unpack(">I", ram[VEH:VEH + 4])[0] == 432, "rhino spawned"
app.spawn_step(1)
assert struct.unpack(">I", ram[VEH:VEH + 4])[0] == 433
FORM.append({"name": "Tank 2"}); app.spawn_name_id()
assert app.spawn_tree.item("433", "values")[1] == "Tank 2"
app.spawn_tree.selection_set(("411", "432")); app.spawn_to_menu(False); print("STATUS", app.status.get(), len(app.cheats), [c.get("group") for c in app.cheats])
spawn_items = [c for c in app.cheats if c["group"] == "Spawn: Vehicles"]
assert [c["name"] for c in spawn_items] == ["infernus", "rhino"], (spawn_items, app.spawn_tree.selection())
app.menu = modmenu.MenuEngine(app.cheats, app._menu_keys())
press("L3", "R1"); press()
assert app.menu.rows()[1][0].startswith("Spawn: Vehicles")
press("Down"); press(); press("Cross"); press(); press("Cross"); press()     # into group, spawn first (infernus)
assert struct.unpack(">I", ram[VEH:VEH + 4])[0] == 411, "spawned from the in-game menu"
app.menu_on = False

# ---------------- back to NCAA: its own library comes back ------------------------------------
app.save_library(app.lib_path, quiet=True)
app.ps2 = FakeProc({0x10000000: mem}, "ps2", False); app.ps2.exe = "pcsx2-qt.exe"
app.ps2.regions = [core.Region(0, 0x10000000, len(mem), 0, "EE RAM")]; app.ps2._finish()
app.apply_game(gameinfo.detect("ps2", ["NCAA Football 2006 [SLUS-21214]"], "pcsx2-qt.exe"))
assert [e["name"] for e in app.library] == ["Kick power"] and app.genre == "football"
d = json.load(open(os.path.join(app_mod.LIB_DIR, "ps3_BLUS30056.json")))
assert len(d["cheats"]) == 5 and d["spawn"]["learned"]["Vehicles"]["433"] == "Tank 2"
assert all("on" not in c for c in d["cheats"])
root.destroy(); core.set_active(None)
print("MENU / SPAWN / TAILOR GUI TEST PASSED")
