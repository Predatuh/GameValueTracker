import sys, struct
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import numpy as np
import ps2core as c


class FakeProc(c.GameTarget):
    """A pretend process: dict of host blocks."""
    def __init__(self, blocks, profile, be, modules=()):
        super().__init__()
        self.blocks = blocks           # host -> bytearray
        self.profile, self.be = profile, be
        self.handle, self.exe, self.pid = 1, "game.exe", 7
        self.modules = list(modules)

    def _find(self, addr, n):
        for h, b in self.blocks.items():
            if h <= addr and addr + n <= h + len(b):
                return b, addr - h
        return None, None

    def read_host(self, addr, size):
        b, o = self._find(addr, size)
        return None if b is None else bytes(b[o:o + size])

    def write_host(self, addr, data):
        b, o = self._find(addr, len(data))
        if b is None:
            return False
        b[o:o + len(data)] = data
        return True

    def _read_region(self, r, out):
        out[r.off:r.off + r.size] = np.frombuffer(self.read_host(r.host, r.size), dtype=np.uint8)


# ---------- big-endian (Dolphin-like): MEM1 at guest 0x80000000, MEM2 at 0x90000000 ----------
H1, H2 = 0x7FF000000000, 0x7FF010000000
mem1, mem2 = bytearray(0x10000), bytearray(0x8000)
mem1[0x1234 * 4:0x1234 * 4 + 4] = struct.pack(">f", 12.5)          # float at guest 800048D0
mem1[0x100:0x102] = struct.pack(">H", 777)                           # u16 at guest 80000100
mem1[0x203] = 99                                                     # byte at guest 80000203
mem2[0x40:0x44] = struct.pack(">I", 123456)                          # u32 at guest 90000040
t = FakeProc({H1: mem1, H2: mem2}, "gcwii", True)
t.regions = [c.Region(0, H1, len(mem1), 0x80000000, "MEM1"), c.Region(0, H2, len(mem2), 0x90000000, "MEM2")]
t._finish()
snap = t.snapshot()
assert len(snap) == len(mem1) + len(mem2)
assert snap.view("<f4")[0x1234] == 12.5
assert t.read(0x1234 * 4, "float") == 12.5
assert c.fa(0x1234 * 4, "float") == "800048D0", c.fa(0x1234 * 4, "float")
assert c.pa("800048D0", "float") == 0x1234 * 4
off2 = len(mem1) + 0x40
assert snap.view("<u4")[off2 // 4] == 123456 and c.fa(off2) == "90000040" and t.read(off2, "u32") == 123456
# scanner finds the u16 and byte; their reads, writes and displayed addresses are the real ones
sc = c.Scanner(); sc.first(snap, "u16", "exact", 777)
hits = [a for a, _, _ in sc.results(snap, 10)]
assert len(hits) == 1 and t.read(hits[0], "u16") == 777 and c.fa(hits[0], "u16") == "80000100", (hits, c.fa(hits[0], "u16"))
sc.first(snap, "byte", "exact", 99)
hb = [a for a, _, _ in sc.results(snap, 50)]
assert any(c.fa(a, "byte") == "80000203" and t.read(a, "byte") == 99 for a in hb)
assert t.write(hits[0], "u16", 1000) and struct.unpack(">H", mem1[0x100:0x102])[0] == 1000
assert t.write(0x1234 * 4, "float", 99.0) and struct.unpack(">f", mem1[0x48D0:0x48D4])[0] == 99.0
assert mem1[0x102:0x104] == b"\0\0", "neighbours untouched"
assert c.pa("80000100", "u16") == hits[0]
print("big-endian OK")

# ---------- PC game: exe .data + heap ------------------------------------------------------
EXE, HEAP = 0x400000, 0x2A300000
data, heap = bytearray(0x2000), bytearray(0x4000)
data[0x10:0x14] = struct.pack("<I", 250)
heap[0x80:0x84] = struct.pack("<f", 3.5)
t = FakeProc({EXE + 0x1000: data, HEAP: heap}, "pc", False, modules=[("game.exe", EXE, 0x10000)])
t.regions = [c.Region(0, EXE + 0x1000, len(data), EXE + 0x1000, "game.exe"),
             c.Region(0, HEAP, len(heap), HEAP, "")]
t._finish()
snap = t.snapshot()
assert c.fa(0x10) == "game.exe+1010" and c.pa("game.exe+1010") == 0x10 and t.read(0x10, "u32") == 250
assert c.fa(len(data) + 0x80) == "2A300080" and c.pa("2A300080") == len(data) + 0x80
assert t.read(c.pa("2A300080"), "float") == 3.5
assert c.MEM_SIZE == len(data) + len(heap)

# ---------- guards -------------------------------------------------------------------------
assert c._online_name("r5apex.exe") and c._online_name("FortniteClient-Win64-Shipping.exe")
assert not c._online_name("gta_sa.exe") and not c._online_name("pcsx2-qt.exe") and not c._online_name("codemaster.exe")
assert c.profile_for_exe("rpcs3.exe") == "ps3" and c.profile_for_exe("Dolphin.exe") == "gcwii"
assert c.profile_for_exe("PPSSPPWindows64.exe") == "psp" and c.profile_for_exe("duckstation-qt-x64-ReleaseLTCG.exe") == "ps1"
assert c.profile_for_exe("gta_sa.exe") == "pc"
c.set_active(None)
print("TARGET TESTS PASSED")
