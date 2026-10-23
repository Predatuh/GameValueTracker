import sys, os, struct
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..")); sys.path.insert(0, ".")
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import numpy as np, tkinter as tk
import ps2core as core
import ps2_tracker as app_mod
exec(open("test_targets.py").read().split("# ---------- big-endian")[0])   # FakeProc

app_mod.SAVE_FILE = os.path.abspath("gui_multi_library.json")
app_mod.SETTINGS_FILE = os.path.abspath("gui_multi_settings.json")
for p in (app_mod.SAVE_FILE, app_mod.SETTINGS_FILE):
    if os.path.exists(p): os.remove(p)
for name in ("showinfo", "showwarning", "showerror"):
    setattr(app_mod.messagebox, name, lambda t, m: print("MSG:", m[:120].replace("\n", " ")))
root = tk.Tk(); app = app_mod.App(root)
app.refresh_processes()

# Dolphin-like big-endian game: health float at guest 80123450, u16 controller at 80456000
H1 = 0x7FF000000000
mem1 = bytearray(0x1800000)
mem1[0x123450:0x123454] = struct.pack(">f", 100.0)
mem1[0x456000:0x456002] = struct.pack(">H", 0x0000)
t = FakeProc({H1: mem1}, "gcwii", True)
t.regions = [core.Region(0, H1, len(mem1), 0x80000000, "MEM1")]
t._finish()
app.ps2 = t
# scan for health like the user would
app.sc_type.set("float") if hasattr(app, "sc_type") else None
snap = t.snapshot()
sc = core.Scanner(); sc.first(snap, "float", "exact", 100.0)
hits = [a for a, _, _ in sc.results(snap, 10)]
assert len(hits) == 1 and core.fa(hits[0], "float") == "80123450"
sc.first(snap, "u16", "exact", 0)
pad = core.pa("80456000", "u16")
assert t.read(pad, "u16") == 0
app.library.append(core.new_value_entry("Health", "Other", hits[0], "float"))
app.library.append(core.new_value_entry("Pad", "Controller", pad, "u16"))
app.cheats.append({"name": "Inf health", "entry": "Health", "value": 999.0, "activator": None})
app.cheats.append({"name": "Health on L+R", "entry": "Health", "value": 500.0,
                   "activator": {"entry": "Pad", "value": 0x0060}})
app.rebuild_library_tree(); app.refresh_cheat_tree(); app.preview_pnach()
txt = app.pnach_text.get("1.0", "end")
print(txt)
assert "04123450 4479C000" in txt                       # 999.0f
assert "28456000 00000060" in txt and "E0000000 80008000" in txt
# library shows emulator addresses
vals = [app.lib_tree.item(i, "values")[0] for c in app.lib_tree.get_children() for i in app.lib_tree.get_children(c)] \
    if hasattr(app, "lib_tree") else []
print("library addresses:", vals)
assert "80123450" in vals and "80456000" in vals
# write through the GUI path changes the real big-endian bytes
assert t.write(hits[0], "float", 250.0) and struct.unpack(">f", mem1[0x123450:0x123454])[0] == 250.0
app.save_library(app_mod.SAVE_FILE, quiet=True)
import json
lib = json.load(open(app_mod.SAVE_FILE))["library"]
assert lib[0]["where"] == "80123450", lib[0]

# PSP / PS1 / PC formats
c = {"name": "x", "entry": "V", "value": 5, "activator": None}
for prof, guest, vt, expect in (("psp", 0x08801000, "u32", "_L 0x20001000 0x00000005"),
                                ("ps1", 0x800C1234, "u16", "800C1234 0005"),
                                ("ps1", 0x800C1234, "byte", "300C1234 0005")):
    host = 0x5000000
    blk = bytearray(0x200000)
    tt = FakeProc({host: blk}, prof, False)
    base_guest = guest & ~0xFFFFF
    tt.regions = [core.Region(0, host, len(blk), base_guest, "")]
    tt._finish()
    lib = [core.new_value_entry("V", "Other", core.pa(f"{guest:08X}", vt), vt)]
    out = core.export_codes(tt, [c], lib, "Game")[0]
    print(prof, vt, out.strip().splitlines()[-1])
    assert expect in out, out
# PC: Cheat Engine table with module+offset
blk = bytearray(0x1000)
tt = FakeProc({0x401000: blk}, "pc", False, modules=[("gta_sa.exe", 0x400000, 0x800000)])
tt.regions = [core.Region(0, 0x401000, len(blk), 0x401000, "gta_sa.exe")]; tt._finish()
ct = core.export_codes(tt, [{"name": "Money", "entry": "M", "value": 999999, "activator": None}],
                       [core.new_value_entry("M", "Other", 0x10, "u32")], "GTA SA")[0]
assert "<Address>gta_sa.exe+1010</Address>" in ct and "4 Bytes" in ct and 'Value="999999"' in ct
root.destroy()
core.set_active(None)
print("MULTI-SYSTEM GUI TEST PASSED")
