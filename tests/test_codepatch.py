import os, sys, shutil, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import ps2core as c

# NOP per CPU
assert c.code_nop("ps2") == 0 and c.code_nop("ps3") == 0x60000000 and c.code_nop("gcwii") == 0x60000000

# each system's own code format
def cp(system, addr, value):
    return c.code_patch_lines({"name": "x", "code": True, "addr": addr, "value": value, "system": system})

assert cp("ps2", 0x00123450, 0) == ["patch=1,EE,00123450,word,00000000"]
assert cp("ps3", 0x00012340, 0x60000000) == ["- [ be32, 0x00012340, 0x60000000 ]"]
assert cp("gcwii", 0x80123454, 0x60000000) == ["04123454 60000000"]
assert cp("psp", 0x08804000, 0) == ["_L 0x20004000 0x00000000"]
assert cp("ps1", 0x80012344, 0x2402FFFF) == ["80012344 FFFF", "80012346 2402"]
# old PS2 patches (no 'system') still export as pnach
assert c.cheat_lines({"name": "a", "code": True, "entry": "(code)", "addr": 0x100000, "value": 0}, []) == \
    ["patch=1,EE,00100000,word,00000000"]
# bad addresses explain themselves
for system, addr, word in (("ps3", 0x00012341, "multiple of 4"), ("gcwii", 0x00001000, "between"),
                           ("pc", 0x1000, "Cheat Engine")):
    try:
        cp(system, addr, 0)
        raise AssertionError("should fail")
    except ValueError as e:
        assert word in str(e), e

# RPCS3 patch.yml
yml = c.rpcs3_patch_yml([{"name": 'No "ammo" used', "addr": 0x00A1B2C0, "value": 0x60000000}],
                        "Mercenaries 2: World in Flames", "BLUS30056", "01.00", "PPU-0123456789abcdef")
print(yml)
assert yml.startswith("Version: 1.2\n\nPPU-0123456789abcdef:\n")
assert '  "No \\"ammo\\" used":' in yml and "BLUS30056: [ 01.00 ]" in yml
assert "      - [ be32, 0x00A1B2C0, 0x60000000 ]" in yml
assert "PPU-PUT_THE_HASH" in c.rpcs3_patch_yml([{"name": "a", "addr": 0x10000, "value": 0x60000000}], "G")

# RPCS3 log -> hash, serial, version, title (latest boot wins)
d = tempfile.mkdtemp()
try:
    with open(os.path.join(d, "RPCS3.log"), "w", encoding="utf-8") as f:
        f.write("·! 0:00:00.1 SYS: Title: Old Game\n·! 0:00:00.2 SYS: Serial: BLES00001\n"
                "·! 0:00:01 LDR: PPU executable hash: PPU-aaaa\n"
                "·! 0:01:00 SYS: Title: Mercenaries 2: World in Flames\n·! 0:01:00 SYS: Serial: BLUS30056\n"
                "·! 0:01:00 SYS: Version: APP_VER=01.00 VERSION=01.00\n"
                "·! 0:01:02 LDR: PPU executable hash: PPU-b6b2b9a5d7b0c1d2e3f4\n")
    info = c.rpcs3_log_info(d)
    print(info)
    assert info == {"hash": "PPU-b6b2b9a5d7b0c1d2e3f4", "serial": "BLUS30056", "version": "01.00",
                    "title": "Mercenaries 2: World in Flames"}
    assert c.rpcs3_log_info(os.path.join(d, "nope"))["hash"] == ""
    # install: creates patches/imported_patch.yml, appends to an existing one, refuses the same game twice
    body = c.rpcs3_patch_yml([{"name": "a", "addr": 0x10000, "value": 0x60000000}], "G", ppu_hash=info["hash"],
                             header=False)
    p = c.rpcs3_install_patch(d, body, info["hash"])
    txt = open(p, encoding="utf-8").read()
    assert txt.startswith("Version: 1.2\n\nPPU-b6b2") and p.endswith(os.path.join("patches", "imported_patch.yml"))
    body2 = c.rpcs3_patch_yml([{"name": "b", "addr": 0x10004, "value": 0x60000000}], "H", ppu_hash="PPU-other",
                              header=False)
    c.rpcs3_install_patch(d, body2, "PPU-other")
    txt = open(p, encoding="utf-8").read()
    assert txt.count("Version: 1.2") == 1 and "PPU-other:" in txt and "PPU-b6b2" in txt
    try:
        c.rpcs3_install_patch(d, body, info["hash"])
        raise AssertionError("duplicate should be refused")
    except ValueError:
        pass
finally:
    shutil.rmtree(d)

# exports for each system include the code patches
class T:
    def __init__(self, prof):
        self.profile, self.be = prof, prof in ("ps3", "gcwii")
patch = {"name": "No reload", "code": True, "entry": "(code)", "addr": 0x80123454, "value": 0x60000000,
         "system": "gcwii"}
text, ext, how = c.export_codes(T("gcwii"), [patch], [], "Game")
print(text)
assert "$No reload\n04123454 60000000" in text and "0x80123454:dword:0x60000000" in text
text, ext, how = c.export_codes(T("ps3"), [dict(patch, system="ps3", addr=0x00012340)], [], "Game")
assert ext == ".yml" and "be32, 0x00012340, 0x60000000" in text and "Game Patches" in how
text, _, _ = c.export_codes(T("psp"), [dict(patch, system="psp", addr=0x08804000, value=0)], [], "Game")
assert "_C1 No reload\n_L 0x20004000 0x00000000" in text
text, _, _ = c.export_codes(T("ps1"), [dict(patch, system="ps1", addr=0x80012344, value=0)], [], "Game")
assert "[No reload]\n80012344 0000\n80012346 0000" in text
# a patch made for another system is left out
text, _, _ = c.export_codes(T("psp"), [patch], [], "Game")
assert "No reload" not in text
print("CODE PATCH TESTS PASSED")
