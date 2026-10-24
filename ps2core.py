"""
ps2core.py - core logic for the Game Value Tracker (PCSX2, RPCS3, Dolphin, PPSSPP, DuckStation, PC games).

Everything here works on plain numpy arrays so it can be tested without
PCSX2. The Windows-only part (attaching to the emulator) is the Pcsx2 class.

PS2 addresses used everywhere are EE RAM offsets: 0x00000000 - 0x01FFFFFF.
"""
import os
import struct
import ctypes

import numpy as np

EE_SIZE = 32 * 1024 * 1024  # PS2 main RAM is 32 MB

# name -> (numpy dtype, struct format, size in bytes, pnach write prefix)
TYPES = {
    "byte":  ("u1",  "<B", 1, "0"),
    "u16":   ("<u2", "<H", 2, "1"),
    "u32":   ("<u4", "<I", 4, "2"),
    "float": ("<f4", "<f", 4, "2"),
}

DEFAULT_CATEGORIES = [
    "Ratings", "Running", "Passing", "Kicking", "Jumping",
    "Defense", "Game State", "Controller", "Other",
]


# --------------------------------------------------------------------------
# Value encoding
# --------------------------------------------------------------------------
def decode(vtype, raw):
    return struct.unpack(TYPES[vtype][1], raw)[0]


def encode(vtype, value):
    fmt = TYPES[vtype][1]
    if vtype == "float":
        return struct.pack(fmt, float(value))
    mask = (1 << (8 * TYPES[vtype][2])) - 1
    return struct.pack(fmt, int(value) & mask)


def parse_number(text, vtype):
    """Accept 123, -5, 0x1F, 1.5 (floats)."""
    text = str(text).strip()
    if vtype == "float":
        return float(text)
    return int(text, 0)


def fmt_value(vtype, value):
    if vtype == "float":
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return f"{value}  (0x{value:X})"


# --------------------------------------------------------------------------
# Windows: attach to a game - PCSX2, other emulators, or any PC game
# --------------------------------------------------------------------------
IS_WIN = os.name == "nt"
PCSX2_NAMES = ("pcsx2-qt.exe", "pcsx2.exe", "pcsx2x64.exe", "pcsx2-avx2.exe")
MEM_SIZE = EE_SIZE            # size of the attached game's memory (updated on attach)

# What kind of game / emulator. Addresses inside the tool are offsets into the game's memory;
# 'guest' is what that system calls the address (what codes and guides use).
PROFILES = {
    "auto":    {"label": "Auto-detect"},
    "ps2":     {"label": "PS2 (PCSX2)", "be": False},
    "ps3":     {"label": "PS3 (RPCS3)", "be": True},
    "gcwii":   {"label": "GameCube / Wii (Dolphin)", "be": True},
    "psp":     {"label": "PSP (PPSSPP)", "be": False},
    "ps1":     {"label": "PS1 (DuckStation)", "be": False},
    "pc":      {"label": "PC game / any program", "be": False},
    "pc_be":   {"label": "Other emulator, big-endian (Cemu, Xenia...)", "be": True},
}
EMU_EXES = (("pcsx2", "ps2"), ("rpcs3", "ps3"), ("dolphin", "gcwii"), ("ppsspp", "psp"),
            ("duckstation", "ps1"))

# Online games with anti-cheat: not supported (offline games and emulators only).
ANTICHEAT_MODULES = ("easyanticheat", "beclient", "battleye", "bedaisy", "gameguard", "npgg",
                     "xigncode", "eaanticheat", "faceit", "pnkbstr", "vgk", "vanguard", "ricochet",
                     "anticheat", "anti-cheat", "hyperion", "equ8", "nprotect", "mhyprot", "acebase")
ONLINE_EXES = ("r5apex", "fortniteclient", "valorant", "cs2", "csgo", "cod", "modernwarfare",
               "blackops", "rainbowsix", "overwatch", "tslgame", "pubg", "dota2", "league of legends",
               "rocketleague", "gta5", "gta5_enhanced", "destiny2", "escapefromtarkov", "rustclient",
               "deadbydaylight", "robloxplayerbeta", "marvel-win64", "discovery", "haloinfinite",
               "eldenring", "dauntless", "warframe", "bf2042", "bf1", "bfv", "fifa", "fc24", "fc25",
               "fc26", "nba2k", "madden", "thefinals", "xdefiant", "splitgate", "naraka", "lostark")


def _online_name(exe):
    n = exe.lower()
    if n.endswith(".exe"):
        n = n[:-4]
    return any(n == x or n.startswith(x + "-") or n.startswith(x + "_") or (len(x) > 5 and n.startswith(x))
               for x in ONLINE_EXES)


def profile_for_exe(exe):
    n = (exe or "").lower()
    for key, prof in EMU_EXES:
        if key in n:
            return prof
    return "pc"


if IS_WIN:
    from ctypes import wintypes as wt

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    u32 = ctypes.WinDLL("user32", use_last_error=True)

    PROCESS_ALL_NEEDED = 0x0010 | 0x0020 | 0x0008 | 0x0400  # VM_READ|VM_WRITE|VM_OPERATION|QUERY_INFORMATION
    TH32CS_SNAPPROCESS = 0x00000002
    TH32CS_SNAPMODULE = 0x00000008
    TH32CS_SNAPMODULE32 = 0x00000010
    INVALID_HANDLE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
            ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
            ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * 260),
        ]

    class MODULEENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD),
            ("th32ProcessID", wt.DWORD), ("GlblcntUsage", wt.DWORD),
            ("ProccntUsage", wt.DWORD), ("modBaseAddr", ctypes.c_void_p),
            ("modBaseSize", wt.DWORD), ("hModule", ctypes.c_void_p),
            ("szModule", ctypes.c_wchar * 256), ("szExePath", ctypes.c_wchar * 260),
        ]

    class MBI(ctypes.Structure):
        _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                    ("AllocationProtect", wt.DWORD), ("PartitionId", wt.WORD),
                    ("RegionSize", ctypes.c_size_t), ("State", wt.DWORD),
                    ("Protect", wt.DWORD), ("Type", wt.DWORD)]

    k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Module32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MODULEENTRY32W)]
    k32.Module32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MODULEENTRY32W)]
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.ReadProcessMemory.restype = wt.BOOL
    k32.WriteProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.WriteProcessMemory.restype = wt.BOOL
    k32.VirtualQueryEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
    k32.VirtualQueryEx.restype = ctypes.c_size_t
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    u32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
    u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    u32.IsWindowVisible.argtypes = [wt.HWND]
    u32.GetWindowTextW.argtypes = [wt.HWND, ctypes.c_wchar_p, ctypes.c_int]
    u32.SendMessageTimeoutW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
                                        ctypes.POINTER(ctypes.c_size_t)]
    u32.SendMessageTimeoutW.restype = ctypes.c_size_t


def list_processes():
    """[(pid, exe, window title)] - programs with a visible window first (that's where games are)."""
    if not IS_WIN:
        return []
    exes = {}
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap not in (None, INVALID_HANDLE):
        try:
            e = PROCESSENTRY32W()
            e.dwSize = ctypes.sizeof(e)
            ok = k32.Process32FirstW(snap, ctypes.byref(e))
            while ok:
                exes[e.th32ProcessID] = e.szExeFile
                ok = k32.Process32NextW(snap, ctypes.byref(e))
        finally:
            k32.CloseHandle(snap)
    titles = {}

    def cb(hwnd, _):
        if u32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(hwnd, buf, 256)
            if buf.value:
                pid = wt.DWORD()
                u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                titles.setdefault(pid.value, (buf.value, hwnd))
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    skip = ("explorer.exe", "textinputhost.exe", "applicationframehost.exe", "systemsettings.exe",
            "shellexperiencehost.exe", "searchhost.exe", "startmenuexperiencehost.exe", "python.exe",
            "pythonw.exe", "ps2tracker.exe", "nvidia overlay.exe", "lockapp.exe")
    out = [(pid, exes.get(pid, "?"), t[0]) for pid, t in titles.items()
           if exes.get(pid, "").lower() not in skip]
    emu = [x for x in out if profile_for_exe(x[1]) != "pc"]
    rest = sorted([x for x in out if x not in emu], key=lambda x: x[1].lower())
    return emu + rest


def window_titles(pid):
    """Every window title of one process (emulators put the game name in one of them)."""
    if not IS_WIN:
        return []
    out = []

    def cb(hwnd, _):
        p = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            buf = ctypes.create_unicode_buffer(512)
            u32.GetWindowTextW(hwnd, buf, 512)
            if buf.value:
                out.append(buf.value)
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


class Region:
    __slots__ = ("off", "host", "size", "guest", "label")

    def __init__(self, off, host, size, guest, label=""):
        self.off, self.host, self.size, self.guest, self.label = off, host, size, guest, label


class GameTarget:
    """
    Attached game memory as one flat block of bytes (offset 0..size). Works for PCSX2, RPCS3,
    Dolphin, PPSSPP, DuckStation and any PC game. Big-endian systems (PS3, GameCube, Wii...)
    are shown byte-swapped per 32-bit word, so floats and 32-bit values scan exactly like a PC game.
    """

    PC_CAP = 1024 << 20            # cap for "any program" (old PC games fit easily)

    def __init__(self):
        self.pid = self.handle = self.exe = None
        self.module_base = None
        self.ee_base = None
        self.base_source = ""
        self.profile = "ps2"
        self.be = False
        self.ptr_size = 4
        self.regions = []
        self.size = 0
        self.modules = []
        self.title = ""

    # ---- process discovery -------------------------------------------
    @staticmethod
    def find_process():
        for pid, exe, _ in list_processes():
            if profile_for_exe(exe) != "pc":            # first emulator that's running
                return pid, exe
        return None, None

    def _modules(self):
        out = []
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, self.pid)
        if snap in (None, INVALID_HANDLE):
            return out
        try:
            e = MODULEENTRY32W()
            e.dwSize = ctypes.sizeof(e)
            ok = k32.Module32FirstW(snap, ctypes.byref(e))
            while ok:
                out.append((e.szModule, e.modBaseAddr or 0, e.modBaseSize))
                ok = k32.Module32NextW(snap, ctypes.byref(e))
        finally:
            k32.CloseHandle(snap)
        return out

    # ---- raw host memory ---------------------------------------------
    def read_host(self, addr, size):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t(0)
        if not k32.ReadProcessMemory(self.handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
            return None
        return buf.raw[:got.value]

    def write_host(self, addr, data):
        got = ctypes.c_size_t(0)
        return bool(k32.WriteProcessMemory(self.handle, ctypes.c_void_p(addr), data,
                                           len(data), ctypes.byref(got)))

    def _query(self, addr):
        m = MBI()
        if not k32.VirtualQueryEx(self.handle, ctypes.c_void_p(addr), ctypes.byref(m), ctypes.sizeof(m)):
            return None
        return m

    def _walk(self, lo=0, hi=1 << 47):
        """Yield (base, size, state, protect, type) for every memory region in [lo, hi)."""
        a = lo
        while a < hi:
            m = self._query(a)
            if m is None or not m.RegionSize:
                break
            base = m.BaseAddress or 0
            yield base, m.RegionSize, m.State, m.Protect, m.Type
            a = base + m.RegionSize

    def _find_export(self, name):
        """Walk the PE export table of the main exe in the live process."""
        base = self.module_base
        hdr = self.read_host(base, 0x400)
        if not hdr or hdr[:2] != b"MZ":
            return None
        pe = struct.unpack_from("<I", hdr, 0x3C)[0]
        opt = pe + 24
        magic = struct.unpack_from("<H", hdr, opt)[0]
        dd = opt + (112 if magic == 0x20B else 96)  # data directory 0 = exports
        exp_rva, exp_size = struct.unpack_from("<II", hdr, dd)
        if not exp_rva:
            return None
        exp = self.read_host(base + exp_rva, 40)
        n_names, a_funcs, a_names, a_ords = struct.unpack_from("<IIII", exp, 24)
        names = self.read_host(base + a_names, 4 * n_names)
        ords = self.read_host(base + a_ords, 2 * n_names)
        target = name.encode()
        for i in range(n_names):
            rva = struct.unpack_from("<I", names, 4 * i)[0]
            s = self.read_host(base + rva, len(target) + 1)
            if s == target + b"\0":
                ordinal = struct.unpack_from("<H", ords, 2 * i)[0]
                f = self.read_host(base + a_funcs + 4 * ordinal, 4)
                return base + struct.unpack("<I", f)[0]
        return None

    def _readable(self, base, size):
        return self.read_host(base, 16) is not None and self.read_host(base + size - 16, 16) is not None

    # ---- attach --------------------------------------------------------
    def attach(self, manual_base=None, pid=None, profile="auto"):
        if not IS_WIN:
            raise RuntimeError("Attaching only works on Windows.")
        self.detach()
        if pid is None:
            self.pid, self.exe = self.find_process()
            if not self.pid:
                raise RuntimeError("Pick your game or emulator in the list first "
                                   "(it has to be running), then click Attach.")
        else:
            self.pid = pid
            self.exe = next((e for p, e, _ in list_processes() if p == pid), None) or "?"
        if _online_name(self.exe):
            raise RuntimeError(f"{self.exe} is an online game with anti-cheat. This tool only works "
                               "with emulators and offline / single-player games.")
        self.handle = k32.OpenProcess(PROCESS_ALL_NEEDED, False, self.pid)
        if not self.handle:
            raise RuntimeError(f"Could not open {self.exe} (error {ctypes.get_last_error()}). "
                               "Try running this tool as administrator.")
        self.modules = self._modules()
        for name, _, _ in self.modules:
            if any(k in name.lower() for k in ANTICHEAT_MODULES):
                self.detach()
                raise RuntimeError(f"{self.exe} has anti-cheat loaded ({name}). This tool only works "
                                   "with emulators and offline / single-player games.")
        self.module_base = next((b for n, b, _ in self.modules if n.lower() == self.exe.lower()), None)
        self.ptr_size = 4
        if profile_for_exe(self.exe) == "pc" or profile in ("pc", "pc_be"):
            wow = wt.BOOL()
            try:
                k32.IsWow64Process(ctypes.c_void_p(self.handle), ctypes.byref(wow))
                self.ptr_size = 4 if wow.value else 8
            except Exception:
                self.ptr_size = 8
        self.profile = profile_for_exe(self.exe) if profile in (None, "auto") else profile
        self.be = PROFILES[self.profile]["be"]
        try:
            getattr(self, "_attach_" + {"pc_be": "pc"}.get(self.profile, self.profile))(manual_base)
        except Exception:
            self.detach()
            raise
        self._finish()

    def _finish(self):
        global MEM_SIZE
        off = 0
        for r in self.regions:
            r.off = off
            off += r.size
        self.size = off
        self._starts = [r.off for r in self.regions]
        self.ee_base = self.regions[0].host if self.regions else None
        MEM_SIZE = self.size
        set_active(self)

    def _attach_ps2(self, manual_base):
        candidates = []
        if manual_base:
            candidates.append((manual_base, "manual"))
        if self.module_base:
            sym = self._find_export("EEmem")
            if sym:
                ptr = self.read_host(sym, 8)
                if ptr:
                    candidates.append((struct.unpack("<Q", ptr)[0], "EEmem export (pointer)"))
                candidates.append((sym, "EEmem export (direct)"))
        candidates.append((0x20000000, "legacy fixed address"))
        for base, src in candidates:
            if base and self._readable(base, EE_SIZE):
                self.regions = [Region(0, base, EE_SIZE, 0, "EE RAM")]
                self.base_source = src
                return
        raise RuntimeError("Found PCSX2 but could not locate PS2 RAM. Make sure a game is "
                           "booted, or enter the base address manually.")

    def _attach_ps1(self, manual_base):
        base, src = manual_base, "manual"
        if not base and self.module_base:
            sym = self._find_export("RAM")
            if sym:
                ptr = self.read_host(sym, 8)
                base, src = (struct.unpack("<Q", ptr)[0] if ptr else None), "RAM export"
                sz = self._find_export("RAM_SIZE")
                raw = self.read_host(sz, 4) if sz else None
                self._ps1_size = struct.unpack("<I", raw)[0] if raw else 0x200000
        size = getattr(self, "_ps1_size", 0x200000) or 0x200000
        if not base or not self._readable(base, size):
            raise RuntimeError("Found DuckStation but not the PS1 RAM. Start a game first.")
        self.regions = [Region(0, base, size, 0x80000000, "PS1 RAM")]
        self.base_source = src

    def _attach_gcwii(self, manual_base):
        MEM1, MEM2 = 0x2000000, 0x4000000
        found = None
        if manual_base:
            found = manual_base
        else:
            for base, size, state, prot, typ in self._walk():
                if size == MEM1 and typ == 0x40000 and state == 0x1000:     # MEM_MAPPED, MEM_COMMIT
                    gid = self.read_host(base, 6) or b""
                    if len(gid) == 6 and all(48 <= c <= 57 or 65 <= c <= 90 for c in gid):
                        found = base
                        break
        if not found:
            raise RuntimeError("Found Dolphin but not the game's RAM. Start a game first.")
        self.regions = [Region(0, found, 0x1800000, 0x80000000, "MEM1")]
        m2 = self._query(found + 0x10000000)
        if m2 is not None and m2.RegionSize == MEM2 and m2.Type == 0x40000 and m2.State == 0x1000:
            self.regions.append(Region(0, found + 0x10000000, MEM2, 0x90000000, "MEM2 (Wii)"))
        self.base_source = "MEM1 found by game ID" if not manual_base else "manual"

    def _attach_psp(self, manual_base):
        base = manual_base
        src = "manual"
        if not base:
            hwnds = []

            def cb(hwnd, _):
                pid = wt.DWORD()
                u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == self.pid:
                    hwnds.append(hwnd)
                return True

            u32.EnumWindows(WNDENUMPROC(cb), 0)
            for msg in (0x8000 + 0x3118, 0x0400 + 0x3118):           # WM_APP / WM_USER + 0x3118
                for h in hwnds:
                    lo, hi = ctypes.c_size_t(0), ctypes.c_size_t(0)
                    u32.SendMessageTimeoutW(h, msg, 0, 0, 2, 500, ctypes.byref(lo))
                    u32.SendMessageTimeoutW(h, msg, 1, 0, 2, 500, ctypes.byref(hi))
                    cand = (hi.value << 32) | (lo.value & 0xFFFFFFFF)
                    if cand and self._readable(cand + 0x08000000, 0x2000000):
                        base, src = cand, "PPSSPP base pointer"
                        break
                if base:
                    break
        if not base or not self._readable(base + 0x08000000, 0x2000000):
            raise RuntimeError("Found PPSSPP but not the PSP RAM. Start a game first (or enter "
                               "the base manually).")
        self.regions = [Region(0, base + 0x08000000, 0x2000000, 0x08000000, "PSP RAM")]
        self.base_source = src

    def _attach_ps3(self, manual_base):
        base = manual_base or 0x300000000
        regs = []
        total = 0
        for b, size, state, prot, typ in self._walk(base, base + 0x40000000):
            if state == 0x1000 and prot & 0xCC and not prot & 0x100:   # committed, writable, no guard
                lo, hi = max(b, base), min(b + size, base + 0x40000000)
                if hi > lo and total < 0x40000000:
                    regs.append(Region(0, lo, hi - lo, lo - base, ""))
                    total += hi - lo
        if not regs:
            raise RuntimeError("Found RPCS3 but not the PS3 memory. Start a game first.")
        self.regions = regs
        self.base_source = f"PS3 memory at host {base:X} ({len(regs)} blocks)"

    def _attach_pc(self, manual_base):
        mods = sorted(self.modules, key=lambda m: m[1])
        regs, total = [], 0
        for b, size, state, prot, typ in self._walk():
            if state != 0x1000 or prot & 0x100 or not prot & 0xCC:      # committed, writable, no guard
                continue
            if typ not in (0x20000, 0x1000000):                          # private or the game's exe/dlls
                continue
            label = ""
            if typ == 0x1000000:
                label = next((n for n, mb, ms in mods if mb <= b < mb + ms), "")
                low = label.lower()
                if low.endswith(".dll") and (low.startswith(("api-ms", "ext-ms")) or low in (
                        "ntdll.dll", "kernel32.dll", "kernelbase.dll", "user32.dll", "gdi32.dll",
                        "ucrtbase.dll", "msvcrt.dll", "combase.dll", "rpcrt4.dll", "win32u.dll")):
                    continue
            if total + size > self.PC_CAP:
                break
            regs.append(Region(0, b, size, b, label))
            total += size
        if not regs:
            raise RuntimeError(f"Could not read any memory from {self.exe}.")
        self.regions = regs
        self.base_source = f"{len(regs)} memory blocks, {total >> 20} MB"

    def detach(self):
        if IS_WIN and self.handle:
            k32.CloseHandle(self.handle)
        self.handle = None
        self.ee_base = None
        self.regions = []

    @property
    def attached(self):
        return self.handle is not None and bool(self.regions)

    def describe(self):
        return f"{PROFILES[self.profile]['label']} - {self.exe} (PID {self.pid}), {self.size >> 20} MB, " \
               f"{self.base_source}"

    # ---- game memory -------------------------------------------------------
    def snapshot(self):
        """Copy all game memory into a numpy uint8 array (big-endian systems: word-swapped)."""
        out = np.empty(self.size, dtype=np.uint8)
        for r in self.regions:
            self._read_region(r, out)
        if self.be:
            out.view(np.uint32).byteswap(inplace=True)
        return out

    def _read_region(self, r, out):
        got = ctypes.c_size_t(0)
        ptr = out.ctypes.data + r.off
        ok = k32.ReadProcessMemory(self.handle, ctypes.c_void_p(r.host), ctypes.c_void_p(ptr),
                                   r.size, ctypes.byref(got))
        if not ok or got.value != r.size:
            chunk = 1 << 16
            for o in range(0, r.size, chunk):
                n = min(chunk, r.size - o)
                if not k32.ReadProcessMemory(self.handle, ctypes.c_void_p(r.host + o),
                                             ctypes.c_void_p(ptr + o), n, ctypes.byref(got)):
                    out[r.off + o:r.off + o + n] = 0

    def _region(self, off):
        import bisect
        i = bisect.bisect_right(self._starts, off) - 1
        if i < 0:
            return None
        r = self.regions[i]
        return r if off < r.off + r.size else None

    def _span(self, off, n):
        """(host address, length, start offset) covering [off, off+n), word-aligned on big-endian."""
        lo, hi = (off & ~3, (off + n + 3) & ~3) if self.be else (off, off + n)
        r = self._region(lo)
        if r is None or hi > r.off + r.size or lo < 0:
            return None
        return r.host + (lo - r.off), hi - lo, lo

    def read_block(self, off, n):
        """Raw bytes [off, off+n) in snapshot layout (word-swapped on big-endian), or None."""
        out = np.zeros(n, np.uint8)
        got_any = False
        pos = off
        while pos < off + n:
            r = self._region(pos)
            if r is None:
                pos = (pos & ~0xFFF) + 0x1000
                continue
            end = min(off + n, r.off + r.size)
            lo, hi = (pos & ~3, (end + 3) & ~3) if self.be else (pos, end)
            hi = min(hi, r.off + r.size)
            raw = self.read_host(r.host + (lo - r.off), hi - lo)
            if raw:
                arr = np.frombuffer(raw, np.uint8)
                if self.be and len(arr) % 4 == 0:
                    arr = arr.view(">u4").astype("<u4").view(np.uint8)
                seg = arr[pos - lo:pos - lo + (end - pos)]
                out[pos - off:pos - off + len(seg)] = seg
                got_any = True
            pos = end
        return out if got_any else None

    def read(self, addr, vtype):
        size = TYPES[vtype][2]
        sp = self._span(addr, size)
        if sp is None:
            return None
        raw = self.read_host(sp[0], sp[1])
        if not raw or len(raw) != sp[1]:
            return None
        if self.be:
            raw = np.frombuffer(raw, dtype=">u4").astype("<u4").tobytes()
            raw = raw[addr - sp[2]:addr - sp[2] + size]
        return decode(vtype, raw)

    def write(self, addr, vtype, value):
        data = encode(vtype, value)
        sp = self._span(addr, len(data))
        if sp is None:
            return False
        if not self.be:
            return self.write_host(sp[0], data)
        raw = self.read_host(sp[0], sp[1])
        if not raw or len(raw) != sp[1]:
            return False
        w = bytearray(np.frombuffer(raw, dtype=">u4").astype("<u4").tobytes())
        w[addr - sp[2]:addr - sp[2] + len(data)] = data
        return self.write_host(sp[0], np.frombuffer(bytes(w), dtype="<u4").astype(">u4").tobytes())

    # ---- addresses people see ----------------------------------------------
    def _xor(self, vtype):
        return {"byte": 3, "u16": 2}.get(vtype, 0) if self.be else 0

    def display_addr(self, off, vtype=None):
        real = off ^ self._xor(vtype)
        r = self._region(real)
        if r is None:
            return f"{off:08X}"
        if self.profile in ("pc", "pc_be"):
            host = r.host + (real - r.off)
            if r.label:
                mb = next((b for n, b, _ in self.modules if n == r.label), None)
                if mb is not None:
                    return f"{r.label}+{host - mb:X}"
            return f"{host:X}"
        return f"{r.guest + (real - r.off):08X}"

    def parse_addr(self, text, vtype=None):
        t = str(text).strip().replace("0x", "").replace("0X", "")
        if "+" in t:
            name, o = t.rsplit("+", 1)
            mb = next((b for n, b, _ in self.modules if n.lower() == name.strip().lower()), None)
            if mb is None:
                raise ValueError(f"{name} isn't loaded in the game")
            v, field = mb + int(o, 16), "host"
        else:
            v, field = int(t, 16), "guest"
        for r in self.regions:
            start = r.host if field == "host" else r.guest
            if start <= v < start + r.size:
                return (r.off + v - start) ^ self._xor(vtype)
        if field == "guest" and 0 <= v < self.size:
            return v
        raise ValueError(f"{t} isn't inside the game's memory")


Pcsx2 = GameTarget                      # old name


# The tool shows and accepts addresses the way the attached system names them.
_ACTIVE = None


def set_active(target):
    global _ACTIVE
    _ACTIVE = target


_TYPE_HINT = {}


def hint(off, vtype):
    """Remember a value's type so messages that only know the address still show the right one
    (on big-endian systems a 16-bit / 8-bit value's real address differs from its offset)."""
    if vtype:
        _TYPE_HINT[int(off)] = vtype
        if len(_TYPE_HINT) > 200000:
            _TYPE_HINT.clear()


def fa(off, vtype=None):
    """Format an internal offset as the address people see for the attached game."""
    if vtype is None:
        vtype = _TYPE_HINT.get(int(off))
    elif vtype in TYPES:
        _TYPE_HINT[int(off)] = vtype
    t = _ACTIVE
    if t is None or not getattr(t, "regions", None):
        return f"{off:08X}"
    try:
        return t.display_addr(off, vtype)
    except Exception:
        return f"{off:08X}"


def looks_like_pointer(target, value, vtype):
    """
    A 4-byte value that holds an address inside the game's own memory - the game follows it, so changing
    it even for a moment usually crashes the game. Tests must never touch these.
    """
    if vtype != "u32" or value is None or getattr(target, "profile", "") in ("pc", "pc_be"):
        return False
    try:
        v = int(value)
    except (TypeError, ValueError):
        return False
    if v < 0x10000 or v % 4:
        return False
    for r in getattr(target, "regions", None) or ():
        if r.guest <= v < r.guest + r.size:
            return True
    return False


def pa(text, vtype=None):
    """Parse an address the user typed / the tool displayed back to an internal offset."""
    t = _ACTIVE
    if t is None or not getattr(t, "regions", None):
        return int(str(text).strip().replace("0x", "").replace("0X", ""), 16)
    return t.parse_addr(text, vtype)


# --------------------------------------------------------------------------
# Scanner (first scan / next scan, like Cheat Engine)
# --------------------------------------------------------------------------
VALUE_MODES = ("exact", "greater than", "less than")
COMPARE_MODES = ("changed", "unchanged", "increased", "decreased")


class Scanner:
    def __init__(self):
        self.reset()

    def reset(self):
        self.vtype = None
        self.idx = None       # element indices still in the running, None = everything
        self.prev = None      # values at the last scan, aligned with idx
        self.count = 0
        self.scans = 0

    @property
    def active(self):
        return self.scans > 0

    def _view(self, snap):
        return snap.view(np.dtype(TYPES[self.vtype][0]))

    @staticmethod
    def _cmp_value(cur, mode, value, vtype):
        if mode == "exact":
            if vtype == "float":
                return np.isclose(cur, value, rtol=1e-3, atol=1e-3)
            return cur == value
        if mode == "greater than":
            return cur > value
        if mode == "less than":
            return cur < value
        raise ValueError(mode)

    @staticmethod
    def _cmp_prev(cur, prev, mode, tol=None):
        # floats get a tiny tolerance: physics values jitter slightly even "at rest"
        if mode == "changed":
            return np.abs(cur - prev) > tol if tol is not None else cur != prev
        if mode == "unchanged":
            return np.abs(cur - prev) <= tol if tol is not None else cur == prev
        t = 0 if tol is None else tol
        if mode == "increased":
            return cur > prev + t
        if mode == "decreased":
            return cur < prev - t
        raise ValueError(mode)

    def first(self, snap, vtype, mode, value=None):
        """mode: 'unknown' or one of VALUE_MODES."""
        self.reset()
        self.vtype = vtype
        v = self._view(snap)
        if mode == "unknown":
            self.idx = None
            self.prev = v.copy()
            self.count = len(v)
        else:
            mask = self._cmp_value(v, mode, value, vtype)
            self.idx = np.flatnonzero(mask).astype(np.int32)
            self.prev = v[self.idx].copy()
            self.count = len(self.idx)
        self.scans = 1
        return self.count

    def next(self, snap, mode, value=None):
        if not self.active:
            raise RuntimeError("Do a first scan before a next scan.")
        v = self._view(snap)
        cur = v if self.idx is None else v[self.idx]
        if mode in VALUE_MODES:
            mask = self._cmp_value(cur, mode, value, self.vtype)
        else:
            if self.vtype == "float":
                with np.errstate(invalid="ignore", over="ignore"):
                    tol = 1e-4 * np.maximum(1.0, np.abs(self.prev))
                    mask = self._cmp_prev(cur, self.prev, mode, tol)
            else:
                mask = self._cmp_prev(cur, self.prev, mode)
        if self.vtype == "float":
            mask &= np.isfinite(cur)
        if self.idx is None:
            self.idx = np.flatnonzero(mask).astype(np.int32)
        else:
            self.idx = self.idx[mask]
        self.prev = cur[mask].copy()
        self.count = len(self.idx)
        self.scans += 1
        return self.count

    def results(self, snap, limit=500):
        """[(ps2_addr, current, previous), ...] for the first `limit` hits."""
        if not self.active or self.idx is None:
            return []
        size = TYPES[self.vtype][2]
        v = self._view(snap)
        idx = self.idx[:limit]
        cur = v[idx]
        prev = self.prev[:limit]
        return [(int(i) * size, cur[n].item(), prev[n].item()) for n, i in enumerate(idx)]


# --------------------------------------------------------------------------
# Ratings / player-record finder
# --------------------------------------------------------------------------
def parse_fields(text):
    """'SPD=92, ACC 88\\nKPW:75' -> [('SPD', 92), ('ACC', 88), ('KPW', 75)]"""
    out = []
    for raw in text.replace(",", "\n").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        for sep in ("=", ":", " "):
            if sep in raw:
                label, val = raw.split(sep, 1)
                break
        else:
            raise ValueError(f"Can't read '{raw}'. Use NAME=VALUE, e.g. SPD=92")
        label = label.strip().upper()
        val = int(val.strip(), 0)
        if not 0 <= val <= 255:
            raise ValueError(f"{label}: ratings must be 0-255 (got {val})")
        out.append((label, val))
    labels = [l for l, _ in out]
    if len(set(labels)) != len(labels):
        raise ValueError("Each rating name can only be used once.")
    if len(out) < 3:
        raise ValueError("Enter at least 3 ratings (5+ works much better).")
    return out


def auto_match(mem, fields_a, fields_b, window=256, max_results=30, max_anchors=1500):
    """
    Quick automatic search from ratings alone (no in-game edits).
    Finds layouts where player 1's AND player 2's ratings sit at the same
    offsets. Works when memory around the roster isn't too noisy; if it
    returns nothing, use the edit method (find_changed_bytes + locate_fields).
    Returns [{'anchor_a', 'anchor_b', 'anchor_label', 'offsets', 'span'}, ...].
    """
    labels_a = [l for l, _ in fields_a]
    vals_b = dict(fields_b)
    missing = [l for l in labels_a if l not in vals_b]
    if missing:
        raise ValueError("Player 2 needs the same rating names: missing " + ", ".join(missing))
    fields_b = [(l, vals_b[l]) for l in labels_a]

    # anchor = label whose value is rarest across both players
    counts = {l: int(np.count_nonzero(mem == dict(fields_a)[l])) +
                 int(np.count_nonzero(mem == vals_b[l])) for l in labels_a}
    anchor = min(counts, key=counts.get)

    A = _anchors_with_all_nearby(mem, fields_a, anchor, window, max_anchors)
    B = _anchors_with_all_nearby(mem, fields_b, anchor, window, max_anchors)
    if A is None or B is None:
        raise ValueError("Too many possible matches for a value-only search. "
                         "Use the edit method instead (change a rating in Edit Player).")
    opts_a = {int(a): locate_fields(mem, int(a), fields_a, window) for a in A}
    out = []
    for a, opts in opts_a.items():
        for b in B:
            b = int(b)
            if b == a:
                continue
            res = resolve_with_second(mem, b, fields_b, opts)
            if all(res[l] for l in labels_a):
                offs = {l: res[l][0] for l in labels_a}
                out.append({"anchor_a": a, "anchor_b": b, "anchor_label": anchor,
                            "offsets": offs,
                            "span": max(offs.values()) - min(offs.values())})
    out.sort(key=lambda r: (r["span"], abs(r["anchor_b"] - r["anchor_a"])))
    out = out[:max_results]
    # the real roster produces a long table of believable players
    for r in out:
        t = detect_table(mem, r["anchor_a"], r["anchor_b"], r["offsets"])
        r["table"] = t
    out.sort(key=lambda r: -(r["table"]["count"] if r["table"] else 0))
    return out


def _anchors_with_all_nearby(mem, fields, anchor, window, max_anchors):
    """Anchor positions that have every other rating somewhere within the window."""
    vals = dict(fields)
    A = np.flatnonzero(mem == vals[anchor]).astype(np.int64)
    n = len(mem)
    lo = np.clip(A - window, 0, n)
    hi = np.clip(A + window + 1, 0, n)
    keep = np.ones(len(A), dtype=bool)
    for label, val in fields:
        if label == anchor:
            continue
        cs = np.concatenate(([0], np.cumsum(mem == val, dtype=np.int32)))
        keep &= (cs[hi] - cs[lo]) > 0
        del cs
    A = A[keep]
    return None if len(A) > max_anchors else A


# ---- the reliable "edit method" ---------------------------------------------
def find_changed_bytes(before, after, old_value, new_value):
    """PS2 addresses where a byte went from old_value to new_value."""
    mask = (before == (old_value & 0xFF)) & (after == (new_value & 0xFF))
    return [int(a) for a in np.flatnonzero(mask)]


def locate_fields(mem, anchor_addr, fields, window=256):
    """
    With one rating's exact address known, find where the player's other
    ratings sit. Returns {label: [offsets relative to anchor_addr]} sorted
    nearest first. One offset = certain; several = needs player 2 to decide.
    """
    lo = max(0, anchor_addr - window)
    hi = min(len(mem), anchor_addr + window + 1)
    region = mem[lo:hi]
    out = {}
    for label, val in fields:
        offs = [int(i) + lo - anchor_addr for i in np.flatnonzero(region == val)]
        offs.sort(key=abs)
        out[label] = offs
    return out


def resolve_with_second(mem, anchor_b, fields_b, options):
    """Keep only offsets where player 2's rating also matches."""
    vals_b = dict(fields_b)
    out = {}
    for label, offs in options.items():
        if label not in vals_b:
            out[label] = offs
            continue
        keep = [o for o in offs
                if 0 <= anchor_b + o < len(mem) and int(mem[anchor_b + o]) == vals_b[label]]
        out[label] = keep
    return out


def _plausible(mem, anchor, offsets, max_rating):
    vals = []
    for off in offsets.values():
        a = anchor + off
        if a < 0 or a >= len(mem):
            return False
        vals.append(int(mem[a]))
    if max(vals) > max_rating:
        return False
    # an all-zero / blank area is not a player
    return sum(v >= 20 for v in vals) >= max(1, len(vals) // 2)


def detect_table(mem, anchor_a, anchor_b, offsets, max_rating=99,
                 min_stride=8, max_stride=8192, max_records=5000):
    """
    Work out the size of one player record (stride) and walk the table.
    Returns {'stride', 'first_anchor', 'count'} or None.
    """
    diff = abs(anchor_b - anchor_a)
    if diff == 0:
        return None
    strides = [s for s in range(min_stride, min(diff, max_stride) + 1) if diff % s == 0]
    best = None
    for s in strides:
        back = 0
        while back < max_records and _plausible(mem, anchor_a - (back + 1) * s, offsets, max_rating):
            back += 1
        fwd = 0
        while fwd < max_records and _plausible(mem, anchor_a + (fwd + 1) * s, offsets, max_rating):
            fwd += 1
        count = back + fwd + 1
        # both players must sit inside the walked table
        lo = anchor_a - back * s
        hi = anchor_a + fwd * s
        if not (lo <= anchor_b <= hi):
            continue
        if best is None or count > best["count"]:
            best = {"stride": s, "first_anchor": lo, "count": count}
    return best


# --------------------------------------------------------------------------
# Library helpers
# --------------------------------------------------------------------------
def new_value_entry(name, category, addr, vtype):
    return {"kind": "value", "name": name, "category": category,
            "addr": int(addr), "type": vtype, "freeze": False, "freeze_value": None}


def new_table_entry(name, category, first_anchor, stride, count, offsets):
    return {"kind": "table", "name": name, "category": category, "type": "byte",
            "base": int(first_anchor), "stride": int(stride), "count": int(count),
            "fields": {k: int(v) for k, v in offsets.items()}}


def table_field_addr(entry, record, field):
    return entry["base"] + record * entry["stride"] + entry["fields"][field]


def table_write_addrs(entry, record, field):
    """
    Every address that holds this player's rating: the main table plus any
    copies the game keeps (a full copy of the roster, or a one-player
    edit/save buffer). Writing all of them stops the game from restoring the
    old value from another copy.
    """
    main = table_field_addr(entry, record, field)
    out = [main]
    for m in entry.get("mirrors", []):
        if m.get("record") is None or m["record"] == record:
            a = main + m["delta"]
            if 0 <= a < MEM_SIZE and a not in out:
                out.append(a)
    return out


def find_copies(mem, entry, record, max_hits=50):
    """
    Look for other places in RAM holding (almost) the same rating bytes as this
    player. A few bytes may differ, because you may already have edited one copy.
    Returns [{'delta', 'record' (None = whole-roster copy), 'addr'}, ...].
    """
    offs = list(entry["fields"].values())
    start = entry["base"] + record * entry["stride"] + min(offs)
    length = max(8, max(offs) - min(offs) + 1)   # just this player's rating bytes
    data = mem.tobytes()
    pat = data[start:start + length]
    target = np.frombuffer(pat, dtype=np.uint8)
    allowed = max(2, length // 6)

    # any exact 4-byte piece of the record suggests where a copy might start
    piece = 4
    votes = {}
    for p0 in range(0, length - piece + 1, piece):
        chunk = pat[p0:p0 + piece]
        if chunk == b"\0" * piece:
            continue
        i, n = data.find(chunk), 0
        while i != -1 and n < 5000:
            cand = i - p0
            if cand != start and 0 <= cand <= len(data) - length:
                votes[cand] = votes.get(cand, 0) + 1
            i, n = data.find(chunk, i + 1), n + 1
    hits = []
    for cand in sorted(votes, key=lambda c: -votes[c]):
        diff = int(np.count_nonzero(mem[cand:cand + length] != target))
        if diff <= allowed and abs(cand - start) >= length:
            hits.append(cand)
            if len(hits) >= max_hits:
                break
    return _classify_copies(mem, entry, record, start, length, sorted(hits), allowed)


def _classify_copies(mem, entry, record, start, length, hits, allowed=0):
    out = []
    s = entry["stride"]
    for h in hits:
        delta = h - start
        # does the next player also match at the same distance? then it's a full roster copy
        nxt = record + 1 if record + 1 < entry["count"] else record - 1
        whole = False
        if 0 <= nxt < entry["count"]:
            a = start + (nxt - record) * s
            b = a + delta
            if 0 <= b and b + length <= len(mem):
                whole = int(np.count_nonzero(mem[a:a + length] != mem[b:b + length])) <= allowed
        out.append({"delta": int(delta), "record": None if whole else record, "addr": int(h)})
    return out


# --------------------------------------------------------------------------
# PCSX2 .pnach cheat generation
# --------------------------------------------------------------------------
def pnach_value_word(vtype, value):
    if vtype == "float":
        return f"{struct.unpack('<I', struct.pack('<f', float(value)))[0]:08X}"
    bits = 8 * TYPES[vtype][2]
    return f"{int(value) & ((1 << bits) - 1):08X}"


def pnach_line(addr, vtype, value):
    if not 0 <= addr < EE_SIZE:
        raise ValueError(f"Address {addr:#x} is outside PS2 RAM")
    if vtype in ("u16",) and addr % 2:
        raise ValueError(f"16-bit address {addr:#x} must be even")
    if vtype in ("u32", "float") and addr % 4:
        raise ValueError(f"32-bit address {addr:#x} must be a multiple of 4")
    prefix = TYPES[vtype][3]
    return f"patch=1,EE,{prefix}{addr:07X},extended,{pnach_value_word(vtype, value)}"


def cheat_lines(cheat, library):
    """
    cheat = {'name', 'entry', 'field' (tables only), 'record' ('all' or int),
             'value', 'activator': None or {'entry', 'value'}}
    """
    if cheat.get("code"):
        # code patch: overwrite one 32-bit MIPS instruction (00000000 = NOP = "skip this line")
        return code_patch_lines(dict(cheat, system="ps2"))
    entry = next((e for e in library if e["name"] == cheat["entry"]), None)
    if entry is None:
        raise ValueError(f"Library entry '{cheat['entry']}' not found")
    if entry["kind"] == "value":
        lines = [pnach_line(entry["addr"], entry["type"], cheat["value"])]
    else:
        recs = range(entry["count"]) if cheat.get("record", "all") == "all" else [int(cheat["record"])]
        lines = [pnach_line(a, "byte", cheat["value"])
                 for r in recs for a in table_write_addrs(entry, r, cheat["field"])]

    act = cheat.get("activator")
    if not act:
        return lines
    ctl = next((e for e in library if e["name"] == act["entry"]), None)
    if ctl is None:
        raise ValueError(f"Activator entry '{act['entry']}' not found")
    if ctl["kind"] != "value" or ctl["type"] != "u16" or ctl["addr"] % 2:
        raise ValueError("The button activator must be a 2-byte (u16) controller value")
    # E-type conditional: E0nnvvvv taaaaaaa -> run next nn lines if u16 at addr == vvvv
    out = []
    for i in range(0, len(lines), 0xFF):
        chunk = lines[i:i + 0xFF]
        out.append(f"patch=1,EE,E0{len(chunk):02X}{int(act['value']) & 0xFFFF:04X},"
                   f"extended,0{ctl['addr']:07X}")
        out.extend(chunk)
    return out


def build_pnach(game_title, cheats, library):
    parts = [f"gametitle={game_title}", ""]
    for c in cheats:
        parts.append(f"[{c['name']}]")
        parts.append("author=PS2 Value Tracker")
        parts.extend(cheat_lines(c, library))
        parts.append("")
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Code patches: replace one CPU instruction in the game ("NOP" = skip that line of code)
# --------------------------------------------------------------------------
# system -> (CPU, NOP instruction, lowest / highest code address, where to find the address)
CODE_SYSTEMS = {
    "ps2":   ("MIPS", 0x00000000, 0x00000000, 0x02000000,
              "PCSX2: Debug > Open Debugger > Breakpoints > New > Memory, tick Write, type the value's "
              "address. Play until it stops - the highlighted line is the instruction."),
    "ps1":   ("MIPS", 0x00000000, 0x80000000, 0x80200000,
              "DuckStation: Debug > CPU Debugger, right-click the value in the memory view > Add write "
              "watchpoint. Play until it stops - the highlighted line is the instruction."),
    "psp":   ("MIPS", 0x00000000, 0x08000000, 0x0A000000,
              "PPSSPP: Debug > Disassembly (or the web debugger), add a memory breakpoint on the value's "
              "address with Write ticked. Play until it stops - copy the instruction's address."),
    "ps3":   ("PowerPC", 0x60000000, 0x00010000, 0x40000000,
              "RPCS3: get the instruction address from a patch guide / the RPCS3 wiki, or from Ghidra with "
              "the PS3 loader (search for the code that writes your value). RPCS3's debugger can't stop on "
              "a write."),
    "gcwii": ("PowerPC", 0x60000000, 0x80000000, 0x81800000,
              "Dolphin: Options > Configuration > Interface > Show Debugging UI. View > Memory, right-click "
              "the value > Set write breakpoint (or Breakpoints > New > Memory, Write). Play until it "
              "stops - the Code view shows the instruction."),
}


def code_nop(system):
    return CODE_SYSTEMS.get(system, CODE_SYSTEMS["ps2"])[1]


def check_code_addr(system, addr):
    """Raises ValueError (plain words) if addr can't be an instruction address on that system."""
    if system not in CODE_SYSTEMS:
        raise ValueError("Code patches work for PS2, PS3, GameCube/Wii, PSP and PS1 games. For PC games use "
                         "Cheat Engine's \"Replace with code that does nothing\".")
    cpu, _, lo, hi, _ = CODE_SYSTEMS[system]
    if addr % 4:
        raise ValueError(f"Code patch address must be a multiple of 4 ({cpu} instructions are 4 bytes)")
    if not lo <= addr < hi:
        raise ValueError(f"Code patch address must be between {lo:08X} and {hi - 1:08X} on this system")


def code_patch_lines(cheat):
    """The code patch in the attached system's own cheat format."""
    system = cheat.get("system", "ps2")
    a, v = int(cheat["addr"]), int(cheat["value"]) & 0xFFFFFFFF
    check_code_addr(system, a)
    if system == "ps2":
        return [f"patch=1,EE,{a:08X},word,{v:08X}"]
    if system == "gcwii":                                  # Gecko 04 = 32-bit write
        return [f"{0x04000000 | (a & 0x01FFFFFF):08X} {v:08X}"]
    if system == "psp":                                    # CWCheat 2 = 32-bit write
        return [f"_L 0x2{(a - 0x08800000) & 0x0FFFFFFF:07X} 0x{v:08X}"]
    if system == "ps1":                                    # GameShark has 16-bit writes: two halves
        g = a & 0x1FFFFF
        return [f"80{g:06X} {v & 0xFFFF:04X}", f"80{g + 2:06X} {v >> 16:04X}"]
    return [f"- [ be32, 0x{a:08X}, 0x{v:08X} ]"]           # ps3: RPCS3 patch.yml


def dolphin_patch_lines(cheat):
    """Dolphin's own patch format (Properties > Patches, or the game's .ini under [OnFrame])."""
    return [f"0x{int(cheat['addr']):08X}:dword:0x{int(cheat['value']) & 0xFFFFFFFF:08X}"]


def _yq(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def rpcs3_patch_yml(patches, title, serial="", app_ver="", ppu_hash="", header=True):
    """
    RPCS3 patch file (Manage > Game Patches). patches = code patch cheats. RPCS3 matches a patch to the
    game by the PPU hash (shown in RPCS3's log when the game boots: 'PPU executable hash: PPU-...').
    """
    key = ppu_hash or "PPU-PUT_THE_HASH_FROM_RPCS3_LOG_HERE"
    out = ["Version: 1.2", ""] if header else []
    out.append(f"{key}:")
    for c in patches:
        out += [f"  {_yq(c['name'])}:",
                "    Games:",
                f"      {_yq(title or 'Game')}:",
                f"        {serial or 'All'}: [ {app_ver or 'All'} ]",
                '    Author: "Game Value Tracker"',
                '    Notes: "Made with Game Value Tracker"',
                "    Patch Version: 1.0",
                "    Patch:",
                "      " + code_patch_lines(dict(c, system="ps3"))[0]]
    return "\n".join(out) + "\n"


def rpcs3_log_info(rpcs3_dir):
    """What RPCS3's log says about the running game: {'hash', 'serial', 'version', 'title'} (any may be '')."""
    import re as _re
    info = {"hash": "", "serial": "", "version": "", "title": ""}
    for name in ("RPCS3.log", os.path.join("log", "RPCS3.log")):
        p = os.path.join(rpcs3_dir or "", name)
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 8_000_000))          # the end is enough (latest boot)
                text = f.read()
        except OSError:
            continue
        for k, pat in (("hash", r"PPU executable hash:\s*(PPU-[0-9a-fA-F]+)"),
                       ("serial", r"\bSerial:\s*([A-Z]{4}\d{5})"),
                       ("version", r"APP_VER=(\d+\.\d+)"),
                       ("title", r"SYS: Title:\s*(.+)")):
            m = _re.findall(pat, text)
            if m:
                info[k] = m[-1].strip()
        break
    return info


def rpcs3_install_patch(rpcs3_dir, yml_body, ppu_hash):
    """
    Add the patches to RPCS3's patches/imported_patch.yml. Returns the file path. Raises ValueError if
    that game already has patches in there (then drag the saved .yml onto RPCS3's patch manager instead).
    """
    pdir = os.path.join(rpcs3_dir, "patches")
    path = os.path.join(pdir, "imported_patch.yml")
    os.makedirs(pdir, exist_ok=True)
    old = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            old = f.read()
    if ppu_hash and f"\n{ppu_hash}:" in "\n" + old:
        raise ValueError("RPCS3 already has patches for this game in imported_patch.yml")
    if not old.strip():
        old = "Version: 1.2\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(old.rstrip("\n") + "\n\n" + yml_body)
    return path


def process_exe_path(pid):
    """Full path of a running program's .exe (Windows), or ''."""
    if not IS_WIN:
        return ""
    h = k32.OpenProcess(0x1000, False, pid)                  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wt.DWORD(1024)
        if k32.QueryFullProcessImageNameW(ctypes.c_void_p(h), 0, buf, ctypes.byref(n)):
            return buf.value
        return ""
    finally:
        k32.CloseHandle(h)


def code_patch_offset(target, cheat):
    """Where a code patch sits in the attached game's memory (internal offset)."""
    return target.parse_addr(f"{int(cheat['addr']):X}", "u32")


# --------------------------------------------------------------------------
# Cheat codes for other systems
# --------------------------------------------------------------------------
def cheat_writes(cheat, library):
    """[(offset, type, value)], activator (offset, value) or None."""
    entry = next((e for e in library if e["name"] == cheat["entry"]), None)
    if entry is None:
        raise ValueError(f"Library entry '{cheat['entry']}' not found")
    if entry["kind"] == "value":
        writes = [(entry["addr"], entry["type"], cheat["value"])]
    else:
        recs = range(entry["count"]) if cheat.get("record", "all") == "all" else [int(cheat["record"])]
        writes = [(a, "byte", cheat["value"]) for r in recs for a in table_write_addrs(entry, r, cheat["field"])]
    act = None
    if cheat.get("activator"):
        ctl = next((e for e in library if e["name"] == cheat["activator"]["entry"]), None)
        if ctl is None or ctl["kind"] != "value" or ctl["type"] != "u16":
            raise ValueError("The button activator must be a 2-byte (u16) controller value")
        act = (ctl["addr"], int(cheat["activator"]["value"]) & 0xFFFF)
    return writes, act


def _guest(off, vt):
    return int(fa(off, vt), 16)


def _bits(vt, v):
    return int(pnach_value_word(vt, v), 16)


def gecko_lines(cheat, library):
    """GameCube / Wii Gecko codes (Dolphin: Properties > Gecko Codes > Add New)."""
    writes, act = cheat_writes(cheat, library)
    out, high = [], False
    if act:
        ga = _guest(act[0], "u16")
        out.append(f"{0x28000000 | (ga & 0x01FFFFFF):08X} 0000{act[1]:04X}")
    for off, vt, v in writes:
        g = _guest(off, vt)
        if (g >> 28) == 0x9 and not high:
            out.append("42000000 90000000")
            high = True
        code = {"byte": 0x00, "u16": 0x02}.get(vt, 0x04) << 24 | (g & 0x01FFFFFF)
        out.append(f"{code:08X} {_bits(vt, v):08X}")
    if act or high:
        out.append("E0000000 80008000")
    return out


def cwcheat_lines(cheat, library):
    """PSP CWCheat codes (PPSSPP)."""
    writes, act = cheat_writes(cheat, library)
    out = []
    for off, vt, v in writes:
        g = _guest(off, vt) - 0x08800000
        if act:
            out.append(f"_L 0xD{(_guest(act[0], 'u16') - 0x08800000) & 0x0FFFFFFF:07X} 0x0000{act[1]:04X}")
        t = {"byte": 0, "u16": 1}.get(vt, 2)
        out.append(f"_L 0x{t}{g & 0x0FFFFFFF:07X} 0x{_bits(vt, v):08X}")
    return out


def gameshark_lines(cheat, library):
    """PS1 GameShark codes (DuckStation: Cheats > Add code > GameShark)."""
    writes, act = cheat_writes(cheat, library)
    out = []

    def cond():
        if act:
            out.append(f"D0{_guest(act[0], 'u16') & 0x1FFFFF:06X} {act[1]:04X}")

    for off, vt, v in writes:
        g = _guest(off, vt) & 0x1FFFFF
        w = _bits(vt, v)
        if vt == "byte":
            cond(); out.append(f"30{g:06X} 00{w & 0xFF:02X}")
        elif vt == "u16":
            cond(); out.append(f"80{g:06X} {w & 0xFFFF:04X}")
        else:
            cond(); out.append(f"80{g:06X} {w & 0xFFFF:04X}")
            cond(); out.append(f"80{g + 2:06X} {w >> 16:04X}")
    return out


def cheat_table(target, cheats, library, title):
    """Cheat Engine table (.CT) - works for PC games and RPCS3."""
    from xml.sax.saxutils import escape
    ce = {"byte": "Byte", "u16": "2 Bytes", "u32": "4 Bytes", "float": "Float"}
    ceb = {"u16": "2 Byte Big Endian", "u32": "4 Byte Big Endian", "float": "Float Big Endian"}
    rows, i = [], 0
    for c in cheats:
        if c.get("code"):
            continue
        writes, _ = cheat_writes(c, library)
        for off, vt, v in writes:
            if target.profile in ("pc", "pc_be"):
                where = target.display_addr(off, vt)
            else:
                real = off ^ target._xor(vt)
                r = target._region(real)
                where = f"{r.host + real - r.off:X}" if r else f"{off:X}"
            vtag = (f"<VariableType>Custom</VariableType><CustomType>{ceb[vt]}</CustomType>"
                    if target.be and vt in ceb else f"<VariableType>{ce[vt]}</VariableType>")
            val = f"{float(v):g}" if vt == "float" else str(int(v))
            rows.append(f'    <CheatEntry>\n      <ID>{i}</ID>\n      <Description>"{escape(c["name"])}"</Description>\n'
                        f'      <LastState Value="{val}" Activated="1"/>\n      {vtag}\n'
                        f'      <Address>{where}</Address>\n    </CheatEntry>')
            i += 1
    return ('<?xml version="1.0" encoding="utf-8"?>\n<CheatTable CheatEngineTableVersion="45">\n'
            f'  <!-- {escape(title)} - made by Game Value Tracker -->\n  <CheatEntries>\n'
            + "\n".join(rows) + "\n  </CheatEntries>\n</CheatTable>\n")


def export_codes(target, cheats, library, title):
    """(text, file extension, how to use) for the attached system."""
    prof = getattr(target, "profile", "ps2")
    named = [c for c in cheats if not c.get("code")]
    codes = [c for c in cheats if c.get("code") and c.get("system", "ps2") == prof]
    if prof == "gcwii":
        body = "\n\n".join(f"${c['name']}\n" + "\n".join(gecko_lines(c, library)) for c in named)
        body += "".join(f"\n\n${c['name']}\n" + "\n".join(code_patch_lines(c)) for c in codes)
        if codes:
            body += ("\n\n# Same code patches in Dolphin's own Patches format (Properties > Patches > Add):\n"
                     + "\n".join(f"# ${c['name']}\n# " + dolphin_patch_lines(c)[0] for c in codes))
        return body.strip("\n") + "\n", ".txt", (
            "Dolphin: right-click the game > Properties > Gecko Codes > Add New. "
            "Paste one code (the lines under its $Name), tick it, restart the game. "
            "Turn on Settings > General > Enable Cheats first.")
    if prof == "psp":
        body = f"_S GAMEID\n_G {title}\n" + "\n".join(
            f"_C1 {c['name']}\n" + "\n".join(cwcheat_lines(c, library) if not c.get("code") else code_patch_lines(c))
            for c in named + codes)
        return body + "\n", ".ini", ("PPSSPP: Game settings > Cheats > Edit cheat file. Paste this in, "
                                     "replace GAMEID with your game ID (shown in PPSSPP's game info), "
                                     "save, then tick the cheats. Turn on Settings > System > Enable cheats.")
    if prof == "ps1":
        body = "\n\n".join(f"[{c['name']}]\n" + "\n".join(
            gameshark_lines(c, library) if not c.get("code") else code_patch_lines(c)) for c in named + codes)
        return body + "\n", ".txt", ("DuckStation: Game Properties > Cheats > Add, set the type to "
                                     "GameShark, paste the lines under one [Name], enable it.")
    if prof == "ps3" and codes and not named:
        return rpcs3_patch_yml(codes, title), ".yml", (
            "RPCS3: Manage > Game Patches, then drag this .yml file onto that window. Tick the patches, "
            "click Save, restart the game.")
    return cheat_table(target, cheats, library, title), ".CT", (
        "Open this .CT in Cheat Engine with the game running. Ticked entries are frozen. "
        + ("Heap addresses change every time the game starts - re-find them next time, or use "
           "Cheat Engine's pointer scan to make them stick." if prof in ("pc", "pc_be") else
           "RPCS3's memory sits at a fixed spot, so these work every session."))


# --------------------------------------------------------------------------
# Recorder analysis: pick out the value that behaves like the ball
# --------------------------------------------------------------------------
KIND_LABELS = {
    "height": "looks like BALL HEIGHT (arcs up then down after the hit)",
    "vspeed": "looks like VERTICAL SPEED (jumps at the hit, then falls steadily)",
    "speed":  "looks like LAUNCH / FORWARD SPEED (jumps at the hit, then holds or slows)",
    "active": "changes during plays, but not in a ball-like way",
    "noise":  "random jitter - probably scratch memory",
    "static": "never changed",
}


def _r2(y, fit):
    ss = float(np.sum((y - np.mean(y)) ** 2))
    return 0.0 if ss <= 1e-12 else max(0.0, 1.0 - float(np.sum((y - fit) ** 2)) / ss)


def analyze_traces(t, traces, marks, window=6.0):
    """
    t: sample times in seconds (1-D array)
    traces: {key: values} sampled at t (floats, NaN where unreadable)
    marks: times (seconds) when you pressed the 'ball hit now' key
    Returns [{'key', 'kind', 'score', 'details'}] best guess first.
    """
    t = np.asarray(t, dtype=float)
    out = []
    in_event = np.zeros(len(t), dtype=bool)
    for m in marks:
        in_event |= (t >= m - 0.3) & (t <= m + window)

    for key, y in traces.items():
        y = np.asarray(y, dtype=float)
        ok = np.isfinite(y)
        if ok.mean() < 0.8 or len(y) < 10:
            out.append({"key": key, "kind": "noise", "score": 0.0, "details": "unreadable"})
            continue
        y = np.where(ok, y, np.nanmedian(y))
        rng = float(np.max(y) - np.min(y))
        if rng < 1e-6:
            out.append({"key": key, "kind": "static", "score": 0.0, "details": "flat"})
            continue

        # smooth physics vs random jitter
        jitter = float(np.median(np.abs(np.diff(y, 2)))) / rng
        smooth = float(np.exp(-40 * jitter))

        # does it move mostly around the hits?
        dy = np.abs(np.diff(y))
        ev, quiet = in_event[1:], ~in_event[1:]
        act_ev = float(dy[ev].mean()) if ev.any() else 0.0
        act_q = float(dy[quiet].mean()) if quiet.any() else 0.0
        focus = act_ev / (act_ev + act_q + 1e-12) if marks else 0.0

        h, vs, sp = [], [], []
        for m in marks:
            # taps can be a bit early or late, so leave a gap around the mark
            after = (t >= m + 0.3) & (t <= m + window)
            before = (t >= m - 0.9) & (t < m - 0.35)
            if after.sum() < 8 or before.sum() < 2:
                continue
            ts, seg = t[after] - m, y[after]
            # follow the flight until the value stops moving (ball landed / caught)
            still = np.abs(np.diff(seg)) <= 1e-6 * rng
            dt = float(np.median(np.diff(ts))) if len(ts) > 1 else 1 / 120
            need = max(3, int(round(0.2 / max(dt, 1e-3))))
            # (a value that is constant from the start - e.g. forward speed with no
            #  drag - isn't "stopped" until it has changed again, e.g. on landing)
            run, cut, moved = 0, len(seg), False
            for i in range(len(still)):
                if still[i]:
                    run += 1
                else:
                    moved, run = moved or i >= 2, 0
                if moved and run >= need and i >= 5:
                    cut = i - run + 1
                    break
            ts, seg = ts[:cut], seg[:cut]
            if len(seg) < 8:
                continue
            jump = abs(float(np.mean(seg[:3])) - float(np.mean(y[before][-3:]))) / rng
            jump_s = min(1.0, jump * 3)

            q = np.polyfit(ts, seg, 2)
            r2q = _r2(seg, np.polyval(q, ts))
            vertex = -q[1] / (2 * q[0]) if q[0] != 0 else -1
            arc = 1.0 if (q[0] < 0 and 0.05 < vertex < ts[-1]) else 0.0
            h.append(r2q * arc)

            l = np.polyfit(ts, seg, 1)
            r2l = _r2(seg, np.polyval(l, ts))
            # vertical speed goes from "up" to "down": it crosses the resting value
            rest = float(np.median(y[~in_event])) if (~in_event).any() else 0.0
            crosses = 1.0 if (seg.max() - rest > 0.1 * rng and rest - seg.min() > 0.1 * rng) else 0.0
            vs.append(r2l * (1.0 if l[0] < 0 else 0.0) * jump_s * crosses)

            hold = 1.0 - min(1.0, float(np.std(seg)) / rng * 2)
            sp.append(jump_s * max(hold, r2l * (1.0 if l[0] <= 0 else 0.3)))

        if not h:
            kind = "active" if smooth > 0.5 else "noise"
            out.append({"key": key, "kind": kind, "score": 0.1 * smooth,
                        "details": "no hit marks inside the recording"})
            continue

        base = smooth * (0.3 + 0.7 * focus)
        scores = {"height": base * float(np.mean(h)),
                  "vspeed": base * float(np.mean(vs)),
                  "speed": base * float(np.mean(sp)) * 0.9}
        kind = max(scores, key=scores.get)
        score = scores[kind]
        if score < 0.25:
            kind = "active" if smooth > 0.5 and focus > 0.5 else "noise"
        out.append({"key": key, "kind": kind, "score": round(score, 3),
                    "details": f"smooth {smooth:.2f}, moves-at-hits {focus:.2f}, "
                               f"arc {np.mean(h):.2f}, fall {np.mean(vs):.2f}, launch {np.mean(sp):.2f}"})
    out.sort(key=lambda r: -r["score"])
    return out


# --------------------------------------------------------------------------
# Power boost: multiply the ball's velocity the moment it's hit
# --------------------------------------------------------------------------
class Booster:
    """
    Feed it the ball's velocity components every few milliseconds.
    When the ball suddenly reverses direction (bat contact), it returns the
    boosted velocity to write back. Pitches (ball starting from rest) and the
    ball slowing or landing don't trigger it.
    """

    def __init__(self, factor=3.0, reverse_only=True, cooldown=1.5, min_jump=0.3, trigger=None):
        self.factor = float(factor)
        # 'reverse' (velocity flips at contact) | 'jump' (big sudden change) | 'change' (any new
        # value the game sets, e.g. a hit-power number written once at contact)
        self.trigger = trigger or ("reverse" if reverse_only else "jump")
        self.reverse_only = self.trigger == "reverse"
        self.cooldown = float(cooldown)
        self.min_jump = float(min_jump)
        self.prev = None
        self.maxmag = 0.0
        self.last_boost = -1e9
        self.count = 0

    def step(self, t, v):
        v = [float(x) for x in v]
        if any(x != x or abs(x) > 1e7 for x in v):  # NaN / garbage
            self.prev = None
            return None
        mag = sum(x * x for x in v) ** 0.5
        self.maxmag = max(self.maxmag, mag)
        out = None
        if self.prev is not None and t - self.last_boost >= self.cooldown:
            p = self.prev
            pm = sum(x * x for x in p) ** 0.5
            floor = 0.05 * self.maxmag
            if self.trigger == "reverse":
                dot = sum(a * b for a, b in zip(v, p))
                trig = mag > floor and pm > floor and dot < 0
            elif self.trigger == "change":
                change = sum((a - b) ** 2 for a, b in zip(v, p)) ** 0.5
                trig = mag > 1e-6 and change > 1e-3 * max(1.0, pm)
            else:
                change = sum((a - b) ** 2 for a, b in zip(v, p)) ** 0.5
                trig = mag > floor and change > self.min_jump * max(mag, pm, 1e-9)
            if trig:
                out = [x * self.factor for x in v]
                self.last_boost = t
                self.count += 1
        self.prev = out if out is not None else v
        return out



# --------------------------------------------------------------------------
# Auto hunt: find the ball in all of RAM with no manual scanning
# --------------------------------------------------------------------------
class AutoHunter:
    """
    Feed it full RAM snapshots (~10-20 per second) and tell it when the ball is
    hit. It narrows 8 million floats down by itself:
      * at every hit, anything that didn't change is removed
      * it counts which values flipped sign at the hit (forward speed reverses
        from 'toward the plate' to 'toward the field')
      * once few enough remain, it records their motion and scores them with
        analyze_traces
    """

    def __init__(self, trace_limit=8000, before=0.6, after=0.6, analyze_after=3.0):
        self.trace_limit = trace_limit
        self.before = before
        self.after = after
        self.analyze_after = analyze_after
        self.ring = []            # [(t, float32 copy)] every ~0.25 s, last ~2 s
        self.pending = []         # marks waiting for their "after" snapshot
        self.marks = []           # all accepted marks
        self.hits = 0
        self.U = None             # surviving float indices
        self.changes = None       # per U: hits where it changed
        self.flips = None         # per U: hits where it flipped sign
        self.traced = None        # float indices being traced
        self.quiet_prev = None    # (t, values of U) from the last quiet check
        self.quiet_changes = None # per U: changed while no play was happening
        self.quiet_checks = 0
        self.trace_neighbours = False
        self.nfloats = 0
        self.trace_t, self.trace_vals = [], []
        self.analyzed_marks = 0
        self.results = []
        self.log = []

    # ---- inputs -------------------------------------------------------------
    BEFORE = (0.7, 0.3)    # seconds before the tap to sample
    AFTER = (0.4, 0.9)     # seconds after the tap to sample

    def mark(self, t):
        if self.marks and t - self.marks[-1] < 1.0:
            return False          # double tap
        before = []
        for off in self.BEFORE:
            cands = [r for r in self.ring if abs(r[0] - (t - off)) <= 0.15]
            if cands:
                before.append(min(cands, key=lambda r: abs(r[0] - (t - off)))[1])
        if not before:
            self.log.append("Ignored a hit tap: the tool needs about a second of watching first.")
            return False
        self.marks.append(t)
        self.pending.append({"m": t, "before": before, "after": []})
        return True

    def feed(self, t, snap):
        f = snap.view("<f4")
        if not self.ring or t - self.ring[-1][0] >= 0.1:
            with np.errstate(over="ignore"):
                self.ring.append((t, f.astype(np.float16)))   # half size; enough for sign/change tests
            self.ring = [r for r in self.ring if t - r[0] <= 1.0]
        if self.traced is not None:
            self.trace_t.append(t)
            self.trace_vals.append(f[self.traced].copy())
            if t - self.trace_t[0] > 120:      # keep the last 2 minutes
                drop = next(i for i, x in enumerate(self.trace_t) if t - x <= 110)
                del self.trace_t[:drop], self.trace_vals[:drop]
        for p in list(self.pending):
            k = len(p["after"])
            if k < len(self.AFTER) and t >= p["m"] + self.AFTER[k]:
                with np.errstate(over="ignore"):
                    p["after"].append(f.astype(np.float16))
            if len(p["after"]) == len(self.AFTER):
                self.pending.remove(p)
                self._apply_hit(p["before"], p["after"], t)
        self._quiet_check(t, f)
        self._maybe_analyze(t)

    def _quiet_check(self, t, f):
        """Between plays: which surviving values still change? (animations, timers)"""
        if self.U is None or len(self.U) == 0 or self.pending:
            return
        if self.marks and t - self.marks[-1] < 3.5:
            return
        if self.quiet_prev is not None and t - self.quiet_prev[0] < 1.0:
            return
        cur = f[self.U].copy()
        if self.quiet_prev is not None and len(self.quiet_prev[1]) == len(cur):
            with np.errstate(invalid="ignore"):
                ch = np.abs(cur - self.quiet_prev[1]) > 1e-5 * np.maximum(1.0, np.abs(cur))
            self.quiet_changes += ch
            self.quiet_checks += 1
        self.quiet_prev = (t, cur)

    def deep_pool(self, limit=4096, exclude=()):
        """Values worth deep-testing: moved at every hit, quiet between plays first."""
        if self.U is None or len(self.U) == 0:
            return []
        busy = (self.quiet_changes / max(1, self.quiet_checks)) if self.quiet_checks else \
            np.zeros(len(self.U))
        order = np.lexsort((-self.flips, busy))          # quiet first, then most reversals
        ex = set(int(e) for e in exclude)
        out = []
        for i in order:
            idx = int(self.U[i])
            if idx in ex or busy[i] > 0.5:
                continue
            out.append(idx)
            if len(out) >= limit:
                break
        return out

    # ---- elimination ------------------------------------------------------
    @staticmethod
    def _valid(x):
        return np.isfinite(x) & (np.abs(x) < 6e4)

    @classmethod
    def _changed(cls, bs, as_):
        """Changed at the hit. 'Garbage before -> real value after' counts as changed
        (values are often uninitialised until the first play)."""
        out = np.zeros(len(bs[0]), dtype=bool)
        ok_after = np.ones(len(bs[0]), dtype=bool)
        for a in as_:
            ok_after &= cls._valid(a)
        for b in bs:
            vb = cls._valid(b)
            for a in as_:
                with np.errstate(invalid="ignore", over="ignore"):
                    bf, af = b.astype(np.float32), a.astype(np.float32)
                    out |= ~vb | (np.abs(af - bf) > 2e-3 * np.maximum(1.0, np.abs(bf)))
        return out & ok_after

    @classmethod
    def _flipped(cls, bs, as_):
        """Same sign for every non-zero sample before, opposite sign for every one after."""
        def side(xs):
            pos = np.zeros(len(xs[0]), dtype=bool)
            neg = np.zeros(len(xs[0]), dtype=bool)
            for x in xs:
                xf = x.astype(np.float32)
                ok = cls._valid(x)
                pos |= ok & (xf > 1e-3)
                neg |= ok & (xf < -1e-3)
            return pos, neg
        bp, bn = side(bs)
        ap, an = side(as_)
        return (bp & ~bn & an & ~ap) | (bn & ~bp & ap & ~an)

    @property
    def allowed_misses(self):
        return max(0, (self.hits - 1) // 3)

    def velocity_set(self):
        """Values that flipped sign at the most hits (ideally every hit)."""
        if self.U is None or len(self.U) == 0:
            return np.array([], dtype=np.int64)
        mx = int(self.flips.max())
        if mx < max(1, self.hits - self.allowed_misses):
            return np.array([], dtype=np.int64)
        return self.U[self.flips == mx]

    def _start_tracing(self, idx, neighbours):
        idx = set(int(i) for i in idx)
        if neighbours:          # position/height usually sit right next to velocity
            for i in list(idx):
                for d in range(-6, 7):
                    if 0 <= i + d < self.nfloats:
                        idx.add(i + d)
        self.traced = np.array(sorted(idx), dtype=np.int64)
        self.trace_t, self.trace_vals = [], []
        self.trace_neighbours = neighbours
        self.analyzed_marks = 0

    def _apply_hit(self, bs, as_, t):
        self.hits += 1
        self.nfloats = len(as_[0])
        if self.U is None:
            self.U = np.flatnonzero(self._changed(bs, as_)).astype(np.int64)
            self.changes = np.ones(len(self.U), dtype=np.int16)
            self.flips = self._flipped([b[self.U] for b in bs], [a[self.U] for a in as_]).astype(np.int16)
        else:
            bu = [b[self.U] for b in bs]
            au = [a[self.U] for a in as_]
            self.changes += self._changed(bu, au)
            self.flips += self._flipped(bu, au)
            keep = (self.hits - self.changes) <= self.allowed_misses
            self.U, self.changes, self.flips = self.U[keep], self.changes[keep], self.flips[keep]
            if self.quiet_changes is not None:
                self.quiet_changes = self.quiet_changes[keep]
            self.quiet_prev = None
        if self.quiet_changes is None or len(self.quiet_changes) != len(self.U):
            self.quiet_changes = np.zeros(len(self.U), dtype=np.int16)
            self.quiet_checks = 0
            self.quiet_prev = None
        vel = self.velocity_set()
        self.log.append(f"Hit {self.hits}: {len(self.U):,} values moved at every hit, "
                        f"{len(vel):,} reversed direction every time like the ball.")
        if self.hits < 2 or len(vel) == 0:
            return
        if self.traced is None and len(vel) * 13 <= self.trace_limit * 2.5:
            self._start_tracing(vel, neighbours=True)
            self.log.append(f"Recording the motion of {len(self.traced):,} values. Keep hitting.")
        elif self.traced is None and len(vel) <= self.trace_limit:
            self._start_tracing(vel, neighbours=False)
            self.log.append(f"Recording the motion of {len(self.traced):,} values. Keep hitting.")
        elif self.traced is not None and not self.trace_neighbours and len(vel) <= 300:
            self._start_tracing(vel, neighbours=True)
            self.log.append(f"Down to {len(vel)} - now also recording the values next to them "
                            f"({len(self.traced):,} total). A couple more hits.")

    # ---- analysis -----------------------------------------------------------
    def _maybe_analyze(self, t):
        if self.traced is None or len(self.trace_t) < 10:
            return
        t0 = self.trace_t[0]
        covered = [m for m in self.marks if m - 0.5 >= t0 and t >= m + self.analyze_after]
        if len(covered) <= self.analyzed_marks:
            return
        self.analyzed_marks = len(covered)
        self.analyze(covered)

    def analyze(self, marks=None):
        if self.traced is None or len(self.trace_t) < 10:
            return []
        if marks is None:
            t0 = self.trace_t[0]
            marks = [m for m in self.marks if m - 0.5 >= t0]
        T = np.array(self.trace_t)
        V = np.stack(self.trace_vals)
        alive = set(int(i) for i in self.U) if self.U is not None else set()
        vel = set(int(i) for i in self.velocity_set())
        flips = dict(zip((int(i) for i in self.U), (int(x) for x in self.flips))) if self.U is not None else {}
        focus = set(vel)
        if self.trace_neighbours:
            focus |= {i + d for i in vel for d in range(-6, 7)}
        cols = [col for col, idx in enumerate(self.traced) if int(idx) in focus] or \
               list(range(len(self.traced)))
        if len(cols) > 3000:   # keep the smoothest movers for the detailed fit
            sub = V[:, cols].astype(float)
            rngs = np.nanmax(sub, 0) - np.nanmin(sub, 0) + 1e-9
            jit = np.nanmedian(np.abs(np.diff(sub, 2, axis=0)), 0) / rngs
            cols = [cols[i] for i in np.argsort(jit)[:3000]]
        traces = {int(self.traced[col]): V[:, col].astype(float) for col in cols}
        res = analyze_traces(T, traces, marks)
        out = []
        for r in res:
            idx = r["key"]
            score = r["score"]
            if idx in vel and r["kind"] in ("speed", "vspeed"):
                score *= 1.3
            if idx not in alive and r["kind"] in ("speed", "vspeed", "height"):
                score *= 0.7           # didn't change at every hit
            out.append({"addr": idx * 4, "kind": r["kind"], "score": round(min(score, 1.5), 3),
                        "flips": flips.get(idx, 0), "hits": self.hits, "details": r["details"]})
        out.sort(key=lambda r: -r["score"])
        self.results = out
        best = out[0] if out else None
        if best and best["score"] >= 0.25:
            self.log.append(f"Analyzed {len(marks)} hit(s). Best: {best['addr']:08X} "
                            f"({KIND_LABELS[best['kind']]}).")
        else:
            self.log.append(f"Analyzed {len(marks)} hit(s). Nothing confident yet - keep hitting.")
        return out

    def best(self, kind):
        return next((r for r in self.results if r["kind"] == kind and r["score"] >= 0.25), None)


class HitDetector:
    """
    Marks a hit automatically from one known ball value, at the moment the ball
    reverses direction: a velocity that flips sign, or a position that was moving
    one way and on the very next sample moves the other way (pitch in, hit out).
    """

    def __init__(self, refractory=2.0):
        self.prev = None
        self.prev_t = None
        self.prev_d = 0.0
        self.sig_d, self.sig_t = None, -1e9
        self.recent_d = []
        self.recent_v = []
        self.last = -1e9
        self.refractory = refractory

    @staticmethod
    def _typical(xs):
        xs = [x for x in xs if x > 0]
        return float(np.percentile(xs, 75)) if len(xs) >= 5 else None

    def step(self, t, v):
        if v is None or v != v or abs(v) > 1e7:
            self.prev = None
            return False
        hit = False
        if self.prev is not None and t > self.prev_t:
            d = (v - self.prev) / (t - self.prev_t)
            typ_d = self._typical(self.recent_d)
            typ_v = self._typical(self.recent_v)
            if t - self.last >= self.refractory:
                big = typ_d is not None and abs(d) > 0.3 * typ_d
                pos_rev = (big and self.sig_d is not None and d * self.sig_d < 0
                           and t - self.sig_t <= 0.25)
                vel_rev = (typ_v is not None and v * self.prev < 0 and
                           min(abs(v), abs(self.prev)) > 0.3 * typ_v)
                if pos_rev or vel_rev:
                    hit = True
                    self.last = t
            if typ_d is not None and abs(d) > 0.3 * typ_d:
                self.sig_d, self.sig_t = d, t      # last real movement
            self.recent_d = (self.recent_d + [abs(d)])[-600:]
            self.prev_d = d
        self.recent_v = (self.recent_v + [abs(v)])[-600:]
        self.prev, self.prev_t = v, t
        return hit


# --------------------------------------------------------------------------
# Auto-tester: write to each candidate and watch what the game does
# --------------------------------------------------------------------------
TEST_VERDICTS = {
    "controls": "CONTROLS IT - the game kept your change and other values reacted",
    "kept":     "game kept the change, but nothing else reacted (may be unused or a setting)",
    "copy":     "COPY - the game overwrote it right away; changing it does nothing",
    "skipped":  "not tested (value was 0 / unreadable at that moment - try again during the action)",
}


def _sample(read, items, secs, rate, sleep, clock):
    """Read every (addr, type) in items for `secs`; returns times and a value matrix."""
    t0 = clock()
    ts, rows = [], []
    while True:
        now = clock() - t0
        ts.append(now)
        rows.append([read(a, vt) for a, vt in items])
        if now >= secs:
            break
        sleep(1 / rate)
    vals = np.array([[np.nan if v is None else float(v) for v in r] for r in rows], dtype=float)
    return np.array(ts), vals


def effect_test(read, write, candidate, others, watchers=(), mode="scale", factor=3.0, delta=7,
                base_secs=0.3, test_secs=0.6, rate=60, restore=True,
                sleep=None, clock=None):
    """
    Write a test value into `candidate` (addr, type) and judge whether it really
    controls the game.
      mode 'scale'  -> value * factor  (speeds, physics)
      mode 'offset' -> value + delta   (ammo, money, health)
    `others`   = the other candidates (copies should follow the real one)
    `watchers` = values that should react (e.g. ball position when testing velocity)
    """
    import time as _t
    sleep = sleep or _t.sleep
    clock = clock or _t.perf_counter
    addr, vt = candidate
    items = [candidate] + list(others) + list(watchers)
    n_oth = len(others)
    tb, before = _sample(read, items, base_secs, rate, sleep, clock)
    o = read(addr, vt)
    if o is None or o != o:
        return {"addr": addr, "type": vt, "verdict": "skipped", "score": 0.0, "note": "unreadable"}
    if mode == "scale":
        if abs(o) < 1e-3:
            return {"addr": addr, "type": vt, "verdict": "skipped", "score": 0.0, "note": "value was 0"}
        w = o * factor
    else:
        w = o + delta
    if vt != "float":
        bits = 8 * TYPES[vt][2]
        w = int(round(w))
        if w >= (1 << bits):
            w = int(o) - delta if mode == "offset" else (1 << bits) - 1
        w = max(0, w)
    write(addr, vt, w)
    ta, after = _sample(read, items, test_secs, rate, sleep, clock)

    # 1) did the game keep it?
    late = after[ta >= min(0.1, test_secs / 2), 0]
    late = late[np.isfinite(late)]
    if len(late) == 0:
        persisted = False
    else:
        scale = max(abs(w - o), 1e-9)
        if mode == "scale":
            # physics keeps evolving; judge on which value it stayed nearer to
            persisted = float(np.median(np.abs(late - w))) < float(np.median(np.abs(late - o)))
        else:
            persisted = float(np.median(np.abs(late - w))) < 0.5 * scale

    # 2) did copies follow?
    followers = []
    for j in range(n_oth):
        b = before[:, 1 + j]
        a = after[ta >= 0.1, 1 + j] if (ta >= 0.1).any() else after[:, 1 + j]
        b, a = b[np.isfinite(b)], a[np.isfinite(a)]
        if not len(b) or not len(a):
            continue
        tol = max(1e-3, 0.02 * abs(o))
        if abs(float(np.median(b)) - o) <= tol and abs(float(np.median(a)) - w) <= max(tol, 0.25 * abs(w - o)):
            followers.append(others[j][0])

    # 3) did anything change speed? (position moving faster after a velocity boost)
    effects = []
    for j in range(len(watchers)):
        col = 1 + n_oth + j
        b, a = before[:, col], after[:, col]
        if np.isfinite(b).sum() < 3 or np.isfinite(a).sum() < 3:
            continue
        rb = np.nanmean(np.abs(np.diff(b))) / max(np.nanmean(np.diff(tb)), 1e-6)
        ra = np.nanmean(np.abs(np.diff(a))) / max(np.nanmean(np.diff(ta)), 1e-6)
        if rb > 1e-6:
            ratio = ra / rb
            if ratio > 1.6 or ratio < 0.6:
                effects.append((watchers[j][0], round(float(ratio), 2)))

    if restore and mode == "offset":
        write(addr, vt, o)
    if persisted and (followers or effects):
        verdict, score = "controls", 1.0 + 0.2 * min(3, len(followers) + len(effects))
    elif persisted:
        verdict, score = "kept", 0.5
    else:
        verdict, score = "copy", 0.0
    note = []
    if followers:
        note.append(f"{len(followers)} cop{'y' if len(followers) == 1 else 'ies'} followed")
    if effects:
        note.append("reacted: " + ", ".join(f"{a:08X} x{r}" for a, r in effects[:3]))
    return {"addr": addr, "type": vt, "verdict": verdict, "score": score,
            "orig": o, "test": w, "followers": followers, "effects": effects,
            "note": "; ".join(note)}


def rank_tests(results):
    """Merge repeated tests of the same address; best controller first."""
    by = {}
    for r in results:
        k = (r["addr"], r["type"])
        by.setdefault(k, []).append(r)
    out = []
    for (addr, vt), rs in by.items():
        tested = [r for r in rs if r["verdict"] != "skipped"]
        if not tested:
            out.append({**rs[-1]})
            continue
        score = sum(r["score"] for r in tested) / len(tested)
        best = max(tested, key=lambda r: r["score"])
        out.append({**best, "score": round(score, 2), "tests": len(tested)})
    out.sort(key=lambda r: -r["score"])
    return out


# --------------------------------------------------------------------------
# Launch predictor: find the target the CPU picked BEFORE it throws
# --------------------------------------------------------------------------
class LaunchPredictor:
    """
    You press a key at the moment of release (pitch, shot, throw).
      phase 'ball'  : find the ball - the value that travels far toward you, one way,
                      right after every release (it doesn't matter if you hit it)
      phase 'learn' : for every pitch, where it crossed the plate (the moment its progress
                      toward you stops - caught OR hit), and what memory looked like during
                      the wind-up
      phase 'ready' : the game's own pre-chosen target, found as either
                        * coordinates  (a float that moves with the location), or
                        * a zone number (the same number always means the same spot -
                          the tool builds the zone table itself)
    """

    PRE = (1.2, 0.5)                  # seconds before release: "already decided" snapshots
    POST = (0.02, 0.1)                # two quick in-flight snapshots right after release
    MAX_POST = 0.42
    MIN_OUTCOMES = 6
    PARTS = ("u32", "b0", "b1", "b2", "b3")

    def __init__(self):
        self.ring = []                # (t, raw RAM snapshot)
        self.pitches = []
        self.phase = "ball"
        self.ball_cand = None
        self.ball_hits = self.ball_sign = self.ball_speed = self.ball_speed2 = None
        self.shortlist = None
        self.sl_sign = self.sl_good = self.sl_disp = None
        self.sl_tracked = 0
        self.ball = None              # float index of the coordinate moving toward you
        self.ball_dir = 1.0
        self.plate = None             # how far along that coordinate the plate is
        self.axis_cols = None
        self.keys = None              # word indices that differ between wind-ups
        self.predictors = {}          # coordinate model: axis -> {...}
        self.zone = None              # zone-number model
        self.candidates = []          # transparent list of what was considered
        self.log = []

    # ---- inputs ------------------------------------------------------------------
    def mark(self, t):
        if self.pitches and t - self.pitches[-1]["t"] < 1.5:
            return False
        pre = {}
        for off in self.PRE:
            near = [r for r in self.ring if abs(r[0] - (t - off)) <= 0.2]
            if near:
                pre[off] = min(near, key=lambda r: abs(r[0] - (t - off)))[1]
        if len(pre) < len(self.PRE):
            self.log.append("Too early - let it watch a couple of seconds before the first pitch.")
            return False
        p = {"t": t, "raw": pre, "prew": None, "post": [], "track": [], "turn": None,
             "outcome": None, "done": False}
        if self.shortlist is not None and self.ball is None:
            p["sl"] = []
            before = [r[1].view("<f4")[self.shortlist].astype(np.float32)
                      for r in self.ring if t - 1.2 <= r[0] <= t]
            if len(before) >= 2:
                with np.errstate(invalid="ignore", over="ignore"):
                    B = np.stack(before)
                    p["sl_pre"] = np.nan_to_num(B.max(0) - B.min(0), nan=1e9, posinf=1e9)
        if self.keys is not None:
            self._shrink(p)
        self.pitches.append(p)
        return True

    def feed(self, t, snap):
        if not self.ring or t - self.ring[-1][0] >= 0.3:
            self.ring.append((t, snap.copy()))
            self.ring = [r for r in self.ring if t - r[0] <= 1.7]
        f = snap.view("<f4")
        for p in self.pitches:
            if p["done"]:
                continue
            dt = t - p["t"]
            if self.ball is None:
                if "sl" in p and dt <= 1.2:
                    p["sl"].append((dt, f[self.shortlist].astype(np.float32)))
                elif "sl" in p and not p.get("sl_done"):
                    p["sl_done"] = True
                    self._judge_flight(p)
                k = len(p["post"])
                if k < len(self.POST) and dt >= self.POST[k]:
                    with np.errstate(over="ignore"):
                        p["post"].append((dt, f.astype(np.float16)))
                if len(p["post"]) == len(self.POST) and not p.get("post_used"):
                    p["post_used"] = True
                    if p["post"][-1][0] <= self.MAX_POST:
                        self._find_ball(p)
                    else:
                        self.log.append("Skipped one pitch - the PC was too slow to catch the ball "
                                        "in the air that time.")
                    p["post"] = []
                if p.get("post_used") and ("sl" not in p or p.get("sl_done")):
                    p["done"] = True
            else:
                if dt <= 1.5:
                    p["track"].append((dt, f[self.ball - 3:self.ball + 4].astype(float)))
                else:
                    p["done"] = True
                    self._finish_pitch(p)
        self._maybe_keys()

    def wants_burst(self):
        return self.ball is None and any(not p["done"] and len(p["post"]) < len(self.POST)
                                         and not p.get("post_used") for p in self.pitches)

    # ---- phase 1: the ball -----------------------------------------------------------
    def _find_ball(self, p):
        (t1, a), (t2, b) = p["post"]
        idx = self.ball_cand
        if idx is not None:
            a, b = a[idx], b[idx]
        a, b = a.astype(np.float32), b.astype(np.float32)
        with np.errstate(invalid="ignore", over="ignore"):
            d1 = (b - a) / max(t2 - t1, 1e-3)
            lin = np.isfinite(d1) & (np.abs(a) < 6e4) & (np.abs(b) < 6e4) & (np.abs(d1) > 1.0)
        n = sum(1 for x in self.pitches if x.get("ball_tested")) + 1
        p["ball_tested"] = True
        if idx is None:
            self.ball_cand = np.flatnonzero(lin).astype(np.int64)
            self.ball_sign = np.sign(d1[self.ball_cand]).astype(np.int8)
            self.ball_hits = np.ones(len(self.ball_cand), dtype=np.int16)
        else:
            good = lin & (np.sign(d1) == self.ball_sign)
            self.ball_hits += good
            keep = (n - self.ball_hits) <= max(0, (n - 1) // 3)
            self.ball_cand, self.ball_sign = self.ball_cand[keep], self.ball_sign[keep]
            self.ball_hits = self.ball_hits[keep]
        self.log.append(f"Pitch {n}: {len(self.ball_cand):,} values shot toward the plate at release.")
        every = self.ball_hits >= n
        if n >= 2 and self.shortlist is None and 0 < int(every.sum()) <= 80000:
            self.shortlist = self.ball_cand[every].copy()
            self.sl_sign = self.ball_sign[every].copy()
            self.sl_good = np.zeros(len(self.shortlist), dtype=np.int16)
            self.sl_disp = np.full(len(self.shortlist), np.inf, dtype=np.float32)   # smallest trip seen
            self.sl_pre = np.zeros(len(self.shortlist), dtype=np.float32)          # most it moved before release
            self.log.append(f"Following {len(self.shortlist):,} of them all the way to the plate.")

    def _judge_flight(self, p):
        """The ball travels far toward the plate, one way, until it's caught or hit."""
        tr = p.get("sl") or []
        if len(tr) < 3:
            self.log.append("Skipped one pitch - not enough samples during the flight.")
            return
        V = np.stack([x[1] for x in tr]) * self.sl_sign[None, :]     # toward the plate = up
        with np.errstate(invalid="ignore", over="ignore"):
            d = np.diff(V, axis=0)
            step = np.nanmax(np.abs(d), axis=0)
            fwd = d > 1e-4 * np.maximum(1.0, step)
            # approach = the forward run from release until progress stops (catch or hit)
            run = np.cumprod(fwd, axis=0)
            nfwd = run.sum(axis=0)
            disp = (np.where(run, d, 0)).sum(axis=0)
        good = (nfwd >= 1) & (disp > 0) & np.isfinite(disp)
        self.sl_tracked += 1
        self.sl_good += good
        # the ball makes the same long trip EVERY pitch; things that just wobble don't
        self.sl_disp = np.minimum(self.sl_disp, np.where(good, disp, np.inf).astype(np.float32))
        if "sl_pre" in p:
            self.sl_pre = np.maximum(self.sl_pre, p["sl_pre"])
        # allow a missed pitch now and then (PC hiccup, mark pressed late)
        ok = self.sl_good >= self.sl_tracked - max(0, (self.sl_tracked - 1) // 3)
        if not ok.any():
            return
        # score: a long trip right after release, from something that sat (fairly) still before it
        trip = np.where(np.isfinite(self.sl_disp), self.sl_disp, 0)
        with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
            avg = np.where(ok & (trip > 0), trip * trip / (self.sl_pre + 0.05 * trip), -1)
        order = np.argsort(-avg)
        top = float(avg[order[0]])
        second = float(avg[order[1]]) if int(ok.sum()) > 1 else 0.0
        if int(ok.sum()) == 1 and self.sl_tracked < 3:
            return
        if (self.sl_tracked >= 2 and top >= 2.0 * max(second, 0)) or top >= 3.0 * max(second, 0):
            self.ball = int(self.shortlist[order[0]])
            self.ball_dir = float(self.sl_sign[order[0]])
            self.phase = "learn"
            self.log.append(f"Found the ball ({self.ball * 4:08X}). Now learning the CPU's targets - "
                            f"keep pressing ] at release, hit or take, about {self.MIN_OUTCOMES} pitches.")

    # ---- phase 2: where each pitch crossed the plate ---------------------------------------
    def _finish_pitch(self, p):
        tr = p["track"]
        if len(tr) < 3:
            return
        Z = np.array([v for _, v in tr])
        prog = Z[:, 3] * self.ball_dir
        k = 0
        for i in range(1, len(prog)):                     # first point where progress stops
            if prog[i] > prog[i - 1] + 1e-4 * max(1.0, abs(prog[i - 1])):
                k = i
            elif k > 0:
                break
        if k == 0:
            return
        # the last forward sample may straddle the plate (caught or hit between two samples), so
        # leave it out and run a line through the clean approach to the plate
        pts = Z[max(0, k - 3):k] if k >= 2 else Z[:k + 1]
        p["turn"] = pts
        p["reach"] = float(prog[k])
        turns = [q["reach"] for q in self.pitches if q.get("reach") is not None]
        self.plate = float(np.percentile(turns, 80))     # how deep pitches get (plate / mitt)
        self._outcomes()
        self._learn()

    def _outcomes(self):
        for q in self.pitches:
            if q["turn"] is None:
                continue
            pts = q["turn"]
            pr = pts[:, 3] * self.ball_dir
            out = pts[-1].copy()
            if len(pts) >= 2 and pr[-1] > pr[0]:
                tgt = min(self.plate, pr[-1] + 2.0 * (pr[-1] - pr[0]) / (len(pts) - 1))
                for col in range(pts.shape[1]):
                    if col != 3:
                        m, c0 = np.polyfit(pr, pts[:, col], 1)
                        out[col] = m * max(tgt, pr[-1]) + c0
            q["outcome"] = out
        outs = np.array([q["outcome"] for q in self.pitches if q["outcome"] is not None])
        if len(outs) >= 3:
            std = np.nanstd(outs, axis=0)
            std[3] = -1
            self.axis_cols = [1, 2] if std[1] > 1e-4 and std[2] > 1e-4 else sorted(np.argsort(-std)[:2])

    # ---- memory that was decided before the pitch -----------------------------------------
    def _maybe_keys(self):
        if self.keys is not None:
            return
        withraw = [p for p in self.pitches if p["raw"]]
        if len(withraw) < 3:
            return
        W = [p["raw"][0.5].view("<u4") for p in withraw[:3]]
        ch = (W[0] != W[1]) | (W[0] != W[2]) | (W[1] != W[2])
        self.keys = np.flatnonzero(ch).astype(np.int64)
        self.log.append(f"{len(self.keys):,} memory values differ between wind-ups - these are the "
                        "suspects.")
        for p in self.pitches:
            self._shrink(p)

    def _shrink(self, p):
        if p["raw"] and self.keys is not None:
            p["prew"] = {off: raw.view("<u4")[self.keys].copy() for off, raw in p["raw"].items()}
            p["raw"] = None

    # ---- phase 3: find the target ---------------------------------------------------------
    def _learn(self):
        rows = [p for p in self.pitches if p["outcome"] is not None and p["prew"] is not None]
        n = len(rows)
        if self.axis_cols is None or self.keys is None or n < self.MIN_OUTCOMES:
            if self.phase == "learn":
                self.log.append(f"Learning: {n}/{self.MIN_OUTCOMES} pitches measured.")
            return
        W05 = np.stack([p["prew"][0.5] for p in rows])
        W12 = np.stack([p["prew"][1.2] for p in rows])
        stable = np.all(W05 == W12, axis=0)                     # set before the wind-up and held
        H = np.array([p["outcome"][self.axis_cols[0]] for p in rows])
        Vv = np.array([p["outcome"][self.axis_cols[1]] for p in rows])
        self.candidates = []

        # (a) coordinates: a float that moves with the location
        F05 = W05.view("<f4")
        coord = {}
        for ax, y in (("h", H), ("v", Vv)):
            if np.std(y) < 1e-6:
                continue
            best = None
            if stable.any() and n >= 6:
                b = self._best_corr(F05[:, stable], y, 0.97)
                if b:
                    best = (int(np.flatnonzero(stable)[b[0]]), b[1])
            if best is None and n >= 10:
                best = self._best_corr(F05, y, 0.98)
            if best:
                j, r = best
                a, b0 = np.polyfit(F05[:, j].astype(float), y, 1)
                coord[ax] = {"idx": int(self.keys[j]), "a": float(a), "b": float(b0), "r": float(r),
                             "early": bool(stable[j]), "n": n}
                self.candidates.append({"addr": int(self.keys[j]) * 4, "kind": f"coordinate ({ax})",
                                        "score": round(abs(r), 3)})

        # (b) zone numbers: the same number always lands in the same spot
        zone = self._best_zone(W05[:, stable], np.flatnonzero(stable), H, Vv) if stable.any() else None

        if len(coord) == 2:
            self.predictors, self.zone = coord, None
            self._ready("coordinates " + ", ".join(f"{k}={v['idx'] * 4:08X} (match {abs(v['r']):.2f})"
                                                   for k, v in coord.items()))
        elif zone:
            self.predictors, self.zone = {}, zone
            self._ready(f"zone number at {zone['addr']:08X} ({zone['part']}), {len(zone['table'])} zones "
                        f"seen, explains {zone['score'] * 100:.0f}% of where pitches go")
        elif self.phase != "ready":
            self.log.append(f"Learning: {n} pitches measured - no clear target yet "
                            f"(zone numbers need a few repeats; usually 8-12 pitches).")

    def _ready(self, what):
        was = self.phase
        self.phase = "ready"
        msg = "TARGET FOUND: " + what
        if was != "ready" or not self.log or self.log[-1] != msg:
            self.log.append(msg)

    @staticmethod
    def _best_corr(X, y, min_r):
        X = X.astype(np.float64)
        with np.errstate(invalid="ignore", over="ignore"):
            ok = np.all(np.isfinite(X), axis=0) & (np.abs(X).max(0) < 1e6) & (np.nanstd(X, 0) > 1e-9)
        if not ok.any():
            return None
        Xc = X[:, ok] - X[:, ok].mean(0)
        yc = y - y.mean()
        den = np.sqrt((Xc ** 2).sum(0) * (yc ** 2).sum())
        r = (Xc * yc[:, None]).sum(0) / np.where(den > 0, den, np.inf)
        k = int(np.argmax(np.abs(r)))
        if abs(r[k]) < min_r:
            return None
        return int(np.flatnonzero(ok)[k]), float(r[k])

    def _best_zone(self, W, cols, H, V):
        """Find a whole number whose value decides the landing spot."""
        n = len(H)
        if n < 8:
            return None
        sst_h = float(((H - H.mean()) ** 2).sum()) or 1e-9
        sst_v = float(((V - V.mean()) ** 2).sum()) or 1e-9
        best = None
        for part in self.PARTS:
            X = W if part == "u32" else (W >> (8 * int(part[1]))) & 0xFF
            for c0 in range(0, X.shape[1], 20000):
                Xc = X[:, c0:c0 + 20000]
                srt = np.sort(Xc, axis=0)
                distinct = 1 + (np.diff(srt, axis=0) != 0).sum(axis=0)
                usable = (distinct >= 3) & (distinct <= n - 2) & (distinct <= 40)
                if not usable.any():
                    continue
                Xu = Xc[:, usable]
                eq = Xu[:, None, :] == Xu[None, :, :]                       # n x n x k
                cnt = eq.sum(axis=1)
                rep = cnt >= 2
                checked = rep.sum(axis=0)
                score = np.full(Xu.shape[1], -1.0)
                for y, sst in ((H, sst_h), (V, sst_v)):
                    tot = (eq * y[None, :, None]).sum(axis=1)
                    with np.errstate(invalid="ignore", divide="ignore"):
                        loo = (tot - y[:, None]) / (cnt - 1)        # predicted from the OTHER pitches
                    err = np.where(rep, (y[:, None] - loo) ** 2, 0).sum(axis=0)
                    spread = np.where(rep, (y[:, None] - y.mean()) ** 2, 0).sum(axis=0)
                    r2 = 1 - err / np.maximum(spread, 1e-9 * sst)
                    score = r2 if score[0] == -1.0 and (score == -1.0).all() else np.minimum(score, r2)
                score = np.where(checked >= 4, score, -1.0)
                rank = score * (0.6 + 0.4 * checked / n)       # a number that repeats more is proven more
                k = int(np.argmax(rank))
                if best is None or rank[k] > best[4]:
                    j = int(self.keys[cols[c0 + np.flatnonzero(usable)[k]]])
                    best = (float(score[k]), j, part, Xu[:, k].copy(), float(rank[k]))
        if best is None or best[0] < 0.85:
            return None
        score, j, part, vals, _ = best
        table = {}
        for val in np.unique(vals):
            m = vals == val
            table[int(val)] = (float(H[m].mean()), float(V[m].mean()), int(m.sum()))
        self.candidates.append({"addr": j * 4, "kind": f"zone number ({part})", "score": round(score, 3)})
        return {"word": j, "addr": j * 4, "part": part, "table": table, "score": score}

    # ---- live ---------------------------------------------------------------------------
    @staticmethod
    def _part(word, part):
        return int(word) if part == "u32" else (int(word) >> (8 * int(part[1]))) & 0xFF

    def predict(self, read):
        """{'h', 'v'} where the pitch is going, or {'zone': n, 'new': True} for an unseen zone."""
        if self.phase != "ready":
            return None
        if self.zone:
            w = read(self.zone["addr"], "u32")
            if w is None:
                return None
            z = self._part(w, self.zone["part"])
            if z in self.zone["table"]:
                h, v, cnt = self.zone["table"][z]
                return {"h": h, "v": v, "zone": z}
            return {"zone": z, "new": True}
        out = {}
        for ax, p in self.predictors.items():
            v = read(p["idx"] * 4, "float")
            if v is None or v != v:
                return None
            out[ax] = p["a"] * v + p["b"]
        return out

    def outcomes(self):
        if not self.axis_cols:
            return []
        return [{"h": float(p["outcome"][self.axis_cols[0]]), "v": float(p["outcome"][self.axis_cols[1]])}
                for p in self.pitches if p["outcome"] is not None]

    def accuracy_report(self):
        if self.phase != "ready" or not self.axis_cols:
            return None
        errs = []
        for p in self.pitches:
            if p["outcome"] is None or p["prew"] is None:
                continue
            j = None
            if self.zone:
                j = int(np.searchsorted(self.keys, self.zone["word"]))
                z = self._part(p["prew"][0.5][j], self.zone["part"])
                if z not in self.zone["table"]:
                    continue
                ph, pv, _ = self.zone["table"][z]
            else:
                vals = {}
                for ax, m in self.predictors.items():
                    jj = int(np.searchsorted(self.keys, m["idx"]))
                    vals[ax] = m["a"] * float(p["prew"][0.5][jj:jj + 1].view("<f4")[0]) + m["b"]
                ph, pv = vals["h"], vals["v"]
            errs.append(max(abs(ph - p["outcome"][self.axis_cols[0]]), abs(pv - p["outcome"][self.axis_cols[1]])))
        if not errs:
            return None
        return {"n": len(errs), "max_err": float(np.max(errs)), "avg_err": float(np.mean(errs))}

    def export(self):
        """Everything learned, for a human (or Claude) to look at."""
        rows = []
        for p in self.pitches:
            if p["outcome"] is None:
                continue
            rows.append({"t": round(p["t"], 2), "h": float(p["outcome"][self.axis_cols[0]]) if self.axis_cols else None,
                         "v": float(p["outcome"][self.axis_cols[1]]) if self.axis_cols else None})
        top = []
        if self.keys is not None:
            done = [p for p in self.pitches if p["prew"] is not None and p["outcome"] is not None]
            if done:
                W05 = np.stack([p["prew"][0.5] for p in done])
                W12 = np.stack([p["prew"][1.2] for p in done])
                stable = np.all(W05 == W12, axis=0)
                for j in np.flatnonzero(stable)[:400]:
                    top.append({"addr": f"{int(self.keys[j]) * 4:08X}",
                                "u32": [int(x) for x in W05[:, j]],
                                "float": [float(x) for x in W05[:, j].view("<f4")]})
        return {"phase": self.phase, "ball": f"{self.ball * 4:08X}" if self.ball is not None else None,
                "plate": self.plate, "axis_cols": self.axis_cols, "pitches": rows,
                "model": ({"zone": {"addr": f"{self.zone['addr']:08X}", "part": self.zone["part"],
                                    "table": self.zone["table"], "score": self.zone["score"]}}
                          if self.zone else {"coordinates": {k: {**v, "addr": f"{v['idx'] * 4:08X}"}
                                                             for k, v in self.predictors.items()}}),
                "candidates": self.candidates, "decided_before_pitch_values": top,
                "log": self.log[-40:]}


# --------------------------------------------------------------------------
# Deep test: change hundreds of values at once, keep halving until one is left
# --------------------------------------------------------------------------
def group_effect_test(read, write, group, watchers, factor=3.0, base_secs=0.15, test_secs=0.35,
                      rate=60, hold=False, sleep=None, clock=None):
    """
    Multiply every float in `group` by `factor` for a moment and watch `watchers`
    (the ball's position values). Before the change, the ball's path is fitted; after
    it, we check whether the ball left that natural path. Returns
    {'result': 'positive'|'negative'|'inconclusive', 'ratio': float, 'written': n}.
    hold=True keeps re-writing during the test (for values the game reads only once).
    Everything is put back afterwards.
    """
    import time as _t
    sleep = sleep or _t.sleep
    clock = clock or _t.perf_counter
    orig = []
    for a in group:
        v = read(a, "float")
        if v is not None and v == v and 1e-6 < abs(v) < 1e6:
            orig.append((a, v))
    if not orig or not watchers:
        return {"result": "inconclusive", "ratio": 1.0, "written": 0}

    def grab(secs, rewrite=False):
        t0, ts, rows = clock(), [], []
        while True:
            now = clock()
            ts.append(now)
            rows.append([read(a, "float") for a in watchers])
            if now - t0 >= secs:
                break
            if rewrite:
                for a, v in orig:
                    write(a, "float", v * factor)
            sleep(1 / rate)
        return np.array(ts), np.array([[np.nan if x is None else float(x) for x in r] for r in rows])

    tb, B = grab(base_secs)
    for a, v in orig:
        write(a, "float", v * factor)
    tw = clock()
    ta, A = grab(test_secs, rewrite=hold)
    for a, v in orig:                       # put everything back
        write(a, "float", v)

    best, any_moving = 0.0, False
    for j in range(len(watchers)):
        b, af = B[:, j], A[:, j]
        okb, oka = np.isfinite(b), np.isfinite(af) & (ta >= tw + 0.08)
        if okb.sum() < 4 or oka.sum() < 2:
            continue
        x0 = tb[okb][-1]
        coef = np.polyfit(tb[okb] - x0, b[okb], 2 if okb.sum() >= 6 else 1)
        pred = np.polyval(coef, ta[oka] - x0)
        disp = abs(float(pred[-1]) - float(b[okb][-1]))       # where it would have gone naturally
        span = float(np.nanmax(b) - np.nanmin(b))
        level = abs(float(b[okb][-1]))
        if disp < 1e-3 and span < 1e-3 and level < 1e-3:
            continue                                   # not moving and zero: tells us nothing
        any_moving = True
        dev = float(np.median(np.abs(af[oka] - pred)))
        # moving values: compare with how far they'd naturally go; steady values (a constant
        # speed): compare with their own size
        best = max(best, dev / max(disp, 0.05 * max(span, 1e-3), 0.2 * level))
    if not any_moving:
        return {"result": "inconclusive", "ratio": 0.0, "written": len(orig)}
    return {"result": "positive" if best > 0.5 else "negative", "ratio": round(best, 2),
            "written": len(orig)}


class GroupTester:
    """Adaptive group testing: test big groups, split the ones that react, drop the rest."""

    def __init__(self, candidates, group_size=512, max_tests=60):
        self.queue = [list(candidates[i:i + group_size]) for i in range(0, len(candidates), group_size)]
        self.found = []
        self.tests = 0
        self.max_tests = max_tests
        self.inconclusive = 0
        self.log = []
        self.total = len(candidates)

    @property
    def done(self):
        return not self.queue or self.tests >= self.max_tests

    def next_group(self):
        return self.queue[0] if self.queue else None

    def record(self, group, res):
        if self.queue and self.queue[0] is group:
            self.queue.pop(0)
        r = res["result"]
        if r == "inconclusive":
            self.inconclusive += 1
            if self.inconclusive <= 20:
                self.queue.insert(0, group)        # try the same group again next time
            return
        self.tests += 1
        if r == "positive":
            if len(group) == 1:
                if any(a == group[0] for a, _ in self.found):
                    return
                self.found.append((group[0], res["ratio"]))
                self.log.append(f"FOUND {group[0] * 4:08X} (ball left its path by {res['ratio']:.1f}x)")
            else:
                h = len(group) // 2
                self.queue[0:0] = [group[:h], group[h:]]
                self.log.append(f"{len(group)} values together moved the ball ({res['ratio']:.1f}) - "
                                f"splitting into {h} + {len(group) - h}")
        else:
            self.log.append(f"{len(group)} values: no effect - ruled out")

    def remaining(self):
        return sum(len(g) for g in self.queue)


# --------------------------------------------------------------------------
# Scan every value type at once (for "is health a float or a byte?")
# --------------------------------------------------------------------------
ALL_TYPES_ORDER = ("u32", "float", "u16", "byte")


class MultiScanner:
    """Same buttons as Scanner, but runs byte / u16 / u32 / float side by side."""

    def __init__(self, types=ALL_TYPES_ORDER):
        self.types = tuple(types)
        self.reset()

    def reset(self):
        self.subs = {vt: Scanner() for vt in self.types}
        self.vtype = "all"
        self.scans = 0

    @property
    def active(self):
        return self.scans > 0

    @property
    def idx(self):
        return None if all(s.idx is None for s in self.subs.values()) else True

    @property
    def count(self):
        return sum(s.count for s in self.subs.values())

    def counts(self):
        return {vt: s.count for vt, s in self.subs.items()}

    def first(self, snap, vtype, mode, value=None):
        self.reset()
        for vt, s in self.subs.items():
            if mode == "unknown":
                s.vtype, s.idx, s.scans = vt, None, 1
                s.prev = snap.view(np.dtype(TYPES[vt][0]))      # one shared copy, no per-type copies
                s.count = len(s.prev)
            elif vt != "float" and value is not None and float(value) != int(float(value)):
                s.vtype, s.idx, s.prev, s.count, s.scans = vt, np.zeros(0, np.int32), np.zeros(0), 0, 1
            else:
                v = value if vt == "float" or value is None else int(float(value))
                if vt != "float" and v is not None and v < 0:
                    v &= (1 << (8 * TYPES[vt][2])) - 1
                s.first(snap, vt, mode, v)
        self.scans = 1
        return self.count

    def next(self, snap, mode, value=None):
        for vt, s in self.subs.items():
            if s.count == 0 and s.idx is not None:
                s.scans += 1
                continue
            if mode in VALUE_MODES and vt != "float" and value is not None:
                if float(value) != int(float(value)):
                    s.idx, s.prev, s.count = np.zeros(0, np.int32), np.zeros(0), 0
                    continue
                s.next(snap, mode, int(float(value)))
            else:
                s.next(snap, mode, value)
        self.scans += 1
        return self.count

    def results_typed(self, snap, limit=500):
        """[(addr, type, current, previous)] - the rarest types first (they're the likeliest)."""
        out = []
        subs = sorted(self.subs.items(), key=lambda kv: (kv[1].count == 0, kv[1].count))
        per = max(limit // max(1, sum(1 for _, s in subs if s.count)), 25)
        for vt, s in subs:
            if s.idx is None or not s.count:
                continue
            for a, cur, prev in s.results(snap, per):
                out.append((a, vt, cur, prev))
        return out[:limit]

    def results(self, snap, limit=500):
        return [(a, c, p) for a, _, c, p in self.results_typed(snap, limit)]


# --------------------------------------------------------------------------
# Recorder events that fit the game (not just "ball hit")
# --------------------------------------------------------------------------
# steps: (what to do, what the value should do): +1 goes up, -1 goes down, "bump" = jumps away
# and comes back (jump height), "change" = becomes a different steady value (weapon / car ID)
EVENT_RECIPES = {
    "ball":     {"label": "Ball is hit / kicked (ball speed & height)", "steps": [("Hit the ball", "ball")]},
    "shoot":    {"label": "Shoot twice, then reload (ammo)",
                 "steps": [("Shoot ONE shot", -1), ("Shoot ONE more shot", -1), ("Reload", +1)]},
    "damage":   {"label": "Take damage, then heal (health / armor)",
                 "steps": [("Take a hit", -1), ("Take another hit", -1), ("Heal / grab health", +1)]},
    "die":      {"label": "Die / lose a life (lives)", "steps": [("Lose a life", -1)]},
    "money":    {"label": "Spend money, then earn some",
                 "steps": [("Buy something", -1), ("Earn / pick up money", +1)]},
    "item":     {"label": "Use an item, then pick one up (item count)",
                 "steps": [("Use ONE item", -1), ("Pick one up", +1)]},
    "jump":     {"label": "Jump (height / vertical speed)", "steps": [("Jump", "bump")]},
    "run":      {"label": "Run, then stop (your speed)", "steps": [("Start running", +1), ("Stop", -1)]},
    "drive":    {"label": "Accelerate, then brake (car speed)",
                 "steps": [("Floor it", +1), ("Brake to a stop", -1)]},
    "lower":    {"label": "Go down to lower ground, then back up (elevation)",
                 "steps": [("Go DOWN to lower ground, stand still", -1), ("Go back UP, stand still", +1)]},
    "score":    {"label": "Score points / runs / goals", "steps": [("Score", +1)]},
    "stamina":  {"label": "Sprint, then rest (stamina / boost meter)",
                 "steps": [("Sprint / use boost until it drops", -1), ("Rest until it refills", +1)]},
    "switch":   {"label": "Switch weapon / car / item (its ID)",
                 "steps": [("Switch to something different", "change")]},
    "timer":    {"label": "Pause, then unpause (clock / timer)",
                 "steps": [("Pause the game", "stop"), ("Unpause", "go")]},
}
EVENT_LABELS = {
    "ball": "moves like the ball (see kinds)",
    "counter": "steps exactly like you did - a counter (ammo, lives, money...)",
    "meter": "goes up and down with you - a meter / amount (health, fuel, speed...)",
    "bump": "jumps away and comes back each time (height / vertical speed)",
    "id": "turns into a different steady number each time (an ID)",
    "clock": "stops when paused and runs when unpaused (a clock)",
    "opposite": "moves the OPPOSITE way every time (a 'used' count, or upside-down axis)",
    "noise": "doesn't follow what you did", "static": "never changed",
}


def analyze_events(t, traces, marks):
    """
    marks: [(time, expect)] with expect from EVENT_RECIPES steps. Returns
    [{'key', 'kind', 'score', 'details'}] best first - for any event, not just a ball hit.
    """
    t = np.asarray(t, float)
    out = []
    mtimes = [m for m, _ in marks]
    for key, y in traces.items():
        y = np.asarray(y, float)
        ok = np.isfinite(y)
        if len(y) < 10 or ok.mean() < 0.8:
            out.append({"key": key, "kind": "noise", "score": 0.0, "details": "unreadable"})
            continue
        y = np.where(ok, y, np.nanmedian(y))
        rng = float(y.max() - y.min())
        if rng < 1e-9:
            out.append({"key": key, "kind": "static", "score": 0.0, "details": "flat"})
            continue
        good = bad = n = 0
        deltas, bumps, ids = [], 0, 0
        near = np.zeros(len(t), bool)
        for i, (m, exp) in enumerate(marks):
            nxt = mtimes[i + 1] if i + 1 < len(marks) else t[-1] + 1
            prv = mtimes[i - 1] if i else -1e9
            before = (t >= max(m - 0.8, prv + 0.3)) & (t < m - 0.12)
            after = (t >= m + 0.25) & (t <= min(m + 1.6, nxt - 0.12))
            near |= (t >= m - 0.2) & (t <= min(m + 2.0, nxt))
            if before.sum() < 2 or after.sum() < 2:
                continue
            b, a = float(np.median(y[before])), float(np.median(y[after]))
            d = a - b
            moved = abs(d) > 1e-6 * max(1.0, abs(b)) and abs(d) > 0.02 * rng
            n += 1
            if exp in (1, -1):
                if moved and np.sign(d) == exp:
                    good += 1
                    deltas.append((exp, abs(d)))
                elif moved:
                    bad += 1
            elif exp == "bump":
                seg = y[(t >= m) & (t <= min(m + 2.0, nxt))]
                if len(seg):
                    peak = float(np.max(np.abs(seg - b)))
                    back = abs(float(seg[-1]) - b) < 0.35 * peak
                    if peak > 0.1 * rng and back:
                        good += 1
            elif exp == "change":
                steady = float(np.ptp(y[after])) <= 1e-6 * max(1.0, abs(a))
                if moved and steady and float(a).is_integer():
                    good += 1
                    ids += 1
            elif exp in ("stop", "go"):
                seg = y[after]
                still = float(np.ptp(seg)) <= 1e-6 * max(1.0, abs(seg[0]))
                if (exp == "stop") == still:
                    good += 1
        if not n:
            out.append({"key": key, "kind": "noise", "score": 0.0, "details": "no events recorded"})
            continue
        quiet_moves = np.abs(np.diff(y))[~near[1:]]
        all_moves = np.abs(np.diff(y))
        quiet = 1.0 - min(1.0, float(quiet_moves.sum()) / (float(all_moves.sum()) + 1e-12)) if len(quiet_moves) else 1.0
        frac = good / n
        kinds = {e for _, e in marks}
        if kinds <= {1, -1} and bad > good:
            kind, frac = "opposite", bad / n * 0.6
        elif "bump" in kinds:
            kind = "bump"
        elif "change" in kinds:
            kind = "id"
        elif kinds & {"stop", "go"}:
            kind = "clock"
        else:
            integerish = all(float(v).is_integer() for v in y[::max(1, len(y) // 200)])
            main = max((1, -1), key=lambda e: sum(1 for x, _ in deltas if x == e))
            dd = [v for x, v in deltas if x == main]
            same = len(dd) >= 2 and np.std(dd) <= 0.25 * np.mean(dd)
            kind = "counter" if integerish and same else "meter"
        score = frac * (0.4 + 0.6 * quiet)
        out.append({"key": key, "kind": kind if frac > 0 else "noise", "score": round(score, 3),
                    "details": f"matched {good}/{n} events, quiet {quiet:.2f}"})
    out.sort(key=lambda r: -r["score"])
    return out


# --------------------------------------------------------------------------
# Values that move around (new address every time the game starts / a level loads)
# --------------------------------------------------------------------------
FP_RADIUS = 96


def read_window(target, snap_or_none, off, vtype, radius=FP_RADIUS):
    """(lo, bytes) around a value, in snapshot layout - cheap even for huge memory."""
    size = TYPES[vtype][2]
    lo = max(0, off - radius)
    hi = off + size + radius
    if snap_or_none is not None:
        return lo, np.asarray(snap_or_none[lo:min(hi, len(snap_or_none))])
    return lo, target.read_block(lo, hi - lo)


def fingerprint(snaps, off, vtype, radius=FP_RADIUS, blocks=None):
    """
    Remember what surrounds a value: the bytes around it that stayed the same over a few snapshots.
    The struct a value lives in usually keeps its shape (max health, flags, IDs...) wherever it moves.
    snaps: full snapshots, or pass blocks=[(lo, bytes), ...] read with read_window.
    """
    size = TYPES[vtype][2]
    if blocks is None:
        lo = max(0, off - radius)
        hi = min(len(snaps[0]), off + size + radius)
        blocks = [np.asarray(s[lo:hi]) for s in snaps]
    else:
        lo = blocks[0][0]
        n = min(len(b) for _, b in blocks)
        blocks = [np.asarray(b[:n]) for _, b in blocks]
        hi = lo + n
    stable = np.ones(hi - lo, bool)
    for b in blocks[1:]:
        stable &= b == blocks[0]
    stable[off - lo:off - lo + size] = False             # the value itself changes
    return {"rel": off - lo, "bytes": blocks[0].tobytes().hex(), "mask": np.packbits(stable).tobytes().hex(),
            "len": hi - lo, "type": vtype}


def _fp_arrays(fp):
    data = np.frombuffer(bytes.fromhex(fp["bytes"]), np.uint8)
    mask = np.unpackbits(np.frombuffer(bytes.fromhex(fp["mask"]), np.uint8))[:fp["len"]].astype(bool)
    return data, mask


def fp_score(snap, fp, off, target=None):
    """How well memory around `off` still matches the fingerprint (0..1). snap may be None (reads live)."""
    data, mask = _fp_arrays(fp)
    lo = off - fp["rel"]
    if lo < 0 or not mask.any():
        return 0.0
    if snap is None:
        seg = target.read_block(lo, fp["len"])
        if seg is None or len(seg) != fp["len"]:
            return 0.0
    else:
        if lo + fp["len"] > len(snap):
            return 0.0
        seg = np.asarray(snap[lo:lo + fp["len"]])
    # judge on the informative bytes (not the empty 00 / FF filler around a struct) when there are enough
    info = mask & (data != 0) & (data != 0xFF)
    use = info if info.sum() >= 8 else mask
    return float((seg[use] == data[use]).mean())


def _anchors(data, mask, n=5, key_len=8):
    """A few short runs of stable, not-boring bytes - several, because any one of them may have changed."""
    ok = list(mask & (data != 0) & (data != 0xFF)) + [False]
    runs, start = [], None
    for i, v in enumerate(ok):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= 4:
                runs.append((start, i))
            start = None
    runs.sort(key=lambda r: -(r[1] - r[0]))
    out = []
    for r0, r1 in runs:
        for k in range(r0, r1 - 3, key_len):                 # split long runs into separate keys
            out.append((k, min(r1, k + key_len)))
    out.sort(key=lambda r: -(r[1] - r[0]))
    return out[:n]


def fp_find(snap, fp, min_score=0.85, limit=2000):
    """[(offset, score)] best first, for where the fingerprinted value is now."""
    data, mask = _fp_arrays(fp)
    size = TYPES[fp["type"]][2]
    align = size if fp["type"] in ("u16", "u32", "float") else 1
    buf = snap.tobytes() if hasattr(snap, "tobytes") else bytes(snap)
    seen, hits = set(), []
    for a0, a1 in _anchors(data, mask):
        key = data[a0:a1].tobytes()
        pos, n = buf.find(key), 0
        while pos != -1 and n < limit:
            n += 1
            off = pos - a0 + fp["rel"]
            if off % align == 0 and off not in seen:
                seen.add(off)
                s = fp_score(snap, fp, off)
                if s >= min_score:
                    hits.append((off, s))
            pos = buf.find(key, pos + 1)
        if hits and max(h[1] for h in hits) >= 0.97:
            break
    hits.sort(key=lambda h: -h[1])
    return hits


def pointer_values_to_offsets(target, words):
    """Turn pointer values found in memory into offsets in our flat memory (-1 = not a pointer)."""
    w = np.asarray(words).astype(np.int64)
    out = np.full(len(w), -1, np.int64)
    prof = getattr(target, "profile", "ps2")
    regions = getattr(target, "regions", None)
    if prof == "ps2" or not regions:
        phys = w & 0x1FFFFFFF
        ok = (phys < MEM_SIZE) & (w != 0) & ((w >> 29) <= 5)
        out[ok] = phys[ok]
        return out
    field = "host" if prof in ("pc", "pc_be") else "guest"
    for r in regions:
        start = getattr(r, field)
        if prof == "ps1":
            m = ((w & 0x1FFFFF) < r.size) & (((w >> 24) == 0x80) | ((w >> 24) == 0x00) | ((w >> 24) == 0xA0))
            out[m] = r.off + (w[m] & 0x1FFFFF)
            continue
        m = (w >= start) & (w < start + r.size)
        out[m] = r.off + (w[m] - start)
    return out


def _ptr_hits(target, snap, tgts, max_back, ptr_size, limit, chunk_words=1 << 24):
    """For each target offset: [(pointer location, distance)] of memory words pointing just below it."""
    dt = "<u8" if ptr_size == 8 else "<u4"
    words = snap[: len(snap) // ptr_size * ptr_size].view(dt)
    res = {t: [] for t in tgts}
    for c0 in range(0, len(words), chunk_words):
        offs = pointer_values_to_offsets(target, words[c0:c0 + chunk_words])
        loc = np.flatnonzero(offs >= 0)
        if not len(loc):
            continue
        val = offs[loc]
        order = np.argsort(val, kind="stable")
        val, loc = val[order], loc[order]
        for t in tgts:
            if len(res[t]) >= limit:
                continue
            i0, i1 = np.searchsorted(val, t - max_back), np.searchsorted(val, t, side="right")
            for k in range(i0, min(i1, i0 + 4 * limit)):
                res[t].append(((c0 + int(loc[k])) * ptr_size, int(t - val[k])))
    for t in tgts:
        res[t].sort(key=lambda h: h[1])
        res[t] = res[t][:limit]
    return res


def pointer_scan(target, snap, off, max_back=0x400, depth=2, limit=40, ptr_size=None):
    """
    Pointer paths to `off`: [(base_offset, [o1, o2...])] where reading the pointer at base, adding
    o1, reading again ... lands on the value. Static bases survive restarts; heap ones get weeded
    out the next time the value is found (prune_paths).
    """
    ptr_size = ptr_size or getattr(target, "ptr_size", 4)
    if len(snap) > (512 << 20):
        depth = 1
    paths, level = [], [(off, [])]
    for _ in range(depth):
        hits = _ptr_hits(target, snap, list({t for t, _ in level}), max_back, ptr_size, limit)
        nxt = []
        for tgt, tail in level:
            for base, d in hits.get(tgt, []):
                p = (base, [d] + tail)
                paths.append(p)
                nxt.append(p)
        level = nxt[:limit]
        if not level:
            break
    statics = [p for p in paths if _is_static(target, p[0])]
    rest = [p for p in paths if not _is_static(target, p[0])]
    return (statics + rest)[:limit * 3]


def _is_static(target, off):
    if getattr(target, "profile", None) in ("pc", "pc_be"):
        r = target._region(off)
        return bool(r and r.label)
    return True


def follow_path(target, base, path, ptr_size=None):
    """Read the pointer chain; returns the value's offset or None."""
    ptr_size = ptr_size or getattr(target, "ptr_size", 4)
    cur = base
    for o in path:
        p = target.read(cur, "u32") if ptr_size == 4 else None
        if ptr_size == 8:
            lo, hi = target.read(cur, "u32"), target.read(cur + 4, "u32")
            p = None if lo is None or hi is None else lo | (hi << 32)
        if p is None:
            return None
        tgt = pointer_values_to_offsets(target, np.array([p], np.int64))[0]
        if tgt < 0:
            return None
        cur = int(tgt) + o
    return cur


def relocate(target, snap, entry):
    """
    Where is this library value now? Uses (1) pointer paths that agree, (2) the fingerprint.
    Returns (offset or None, how).
    """
    vt = entry["type"]
    fp = entry.get("fp")
    ps = entry.get("ptr_size") or getattr(target, "ptr_size", 4)
    votes = {}
    for base, path in entry.get("paths", [])[:120]:
        o = follow_path(target, base, path, ps)
        if o is not None and 0 <= o < len(snap):
            votes[o] = votes.get(o, 0) + 1
    if fp and fp_score(snap, fp, entry["addr"]) >= 0.9:
        return entry["addr"], "still in place"
    if votes:
        best = max(votes, key=lambda o: (votes[o], fp_score(snap, fp, o) if fp else 0))
        if not fp or entry.get("paths_ok") or fp_score(snap, fp, best) >= 0.6 or votes[best] >= 3:
            return best, f"pointer paths ({votes[best]} agree)"
    if fp:
        hits = fp_find(snap, fp)
        if hits and (len(hits) == 1 or hits[0][1] - hits[1][1] > 0.03):
            return hits[0][0], f"fingerprint match {hits[0][1] * 100:.0f}%"
        if hits:
            near = min(hits[:20], key=lambda h: abs(h[0] - entry["addr"]))
            return near[0], f"fingerprint ({len(hits)} look-alikes, picked the closest)"
        if fp_score(snap, fp, entry["addr"]) >= 0.5:
            return entry["addr"], "probably still in place"
    return None, "not found"


def prune_paths(target, entry, true_off):
    """Keep only the pointer paths that still lead to the value (static ones survive)."""
    ps = entry.get("ptr_size") or getattr(target, "ptr_size", 4)
    keep = [(b, p) for b, p in entry.get("paths", []) if follow_path(target, b, p, ps) == true_off]
    if len(keep) < len(entry.get("paths", [])) and keep:
        entry["paths_ok"] = True          # survived a move: these are the real (static) paths
    entry["paths"] = keep
    return len(keep)


# --------------------------------------------------------------------------
# Pulse hunt: things that go up and come back (jump height, run speed, car speed)
# --------------------------------------------------------------------------
class PulseHunter:
    """
    You press ] and do the thing once (jump / run 2 s / floor it), then stop.
    Snapshots: at the press (before), part way through (mid), and after you've stopped (post).
    The value we want moved away at mid and came back by post, the same way every time, and sat
    still while you stood still between tries. Rise-and-fall happens in one go - no "now go down".
    """

    TYPES = ("float", "u32", "u16")

    def __init__(self, mid=0.45, post=2.2, target=6):
        self.mid, self.post, self.target = mid, post, target
        self.idx = {}           # type -> indices still in the running
        self.sign = {}          # type -> +1/-1 per index (which way it moved the first time)
        self.last_post = None
        self.pulses = 0
        self.log = []

    @staticmethod
    def _v(snap, vt):
        return snap.view(np.dtype(TYPES[vt][0]))

    def add(self, pre, mid, post):
        """One try. Returns how many candidates are left."""
        for vt in self.TYPES:
            a, b, c = (self._v(s, vt) for s in (pre, mid, post))
            idx = self.idx.get(vt)
            if idx is not None:
                a, b, c = a[idx], b[idx], c[idx]
            with np.errstate(invalid="ignore", over="ignore"):
                a64, b64, c64 = a.astype(np.float64), b.astype(np.float64), c.astype(np.float64)
                d1, d2 = b64 - a64, c64 - a64
                tiny = 1e-4 * np.maximum(1.0, np.abs(a64)) if vt == "float" else 0.5
                keep = np.isfinite(d1) & np.isfinite(d2) & (np.abs(d1) > tiny) & (np.abs(d2) <= 0.3 * np.abs(d1))
                if vt == "float":
                    keep &= (np.abs(a64) < 1e7) & (np.abs(b64) < 1e7)
                if self.last_post is not None and vt in self.idx:
                    lp = self._v(self.last_post, vt)[idx].astype(np.float64)
                    keep &= np.abs(a64 - lp) <= np.maximum(0.3 * np.abs(d1), tiny)   # still while idle
            sg = np.sign(np.nan_to_num(d1)).astype(np.int8)
            if idx is None:
                self.idx[vt] = np.flatnonzero(keep).astype(np.int64)
                self.sign[vt] = sg[keep]
            else:
                keep &= sg == self.sign[vt]
                self.idx[vt] = idx[keep]
                self.sign[vt] = self.sign[vt][keep]
        self.last_post = post
        self.last_mid = mid
        self.pulses += 1
        n = self.count
        self.log.append(f"Try {self.pulses}: {n:,} values rose and came back.")
        return n

    @property
    def count(self):
        return sum(len(v) for v in self.idx.values())

    @property
    def done(self):
        return self.pulses >= 2 and 0 < self.count <= self.target

    def candidates(self, limit=5000):
        """[(addr, type)] - floats first, then whole numbers."""
        out = []
        for vt in self.TYPES:
            size = TYPES[vt][2]
            out += [(int(i) * size, vt) for i in self.idx.get(vt, [])]
        taken, res = set(), []
        for a, vt in out:
            span = range(a, a + TYPES[vt][2])
            if any(x in taken for x in span):
                continue
            taken.update(span)
            res.append((a, vt))
            if len(res) >= limit:
                break
        return res


# --------------------------------------------------------------------------
# Test-with-me: freeze (or boost) a big group, you say if the game reacted, halve, repeat
# --------------------------------------------------------------------------
class HumanGroupTest:
    """
    Binary search with you as the judge. Hold half the candidates (or multiply them for a speed
    hack); you say YES (it worked - e.g. you can't run / you're super fast) or NO.
    ~log2(N) questions: 500 candidates -> about 9 tries.
    """

    MAX_GROUP = 1500

    def __init__(self, candidates):
        self.left = list(dict.fromkeys(candidates))
        self.found = None
        self.failed = False
        self.group = None
        self.asked = 0
        self.confirming = False

    @property
    def done(self):
        return self.found is not None or self.failed

    def next_group(self):
        if self.done:
            return None
        if len(self.left) == 1:
            self.confirming = True
            self.group = list(self.left)
        else:
            half = min(self.MAX_GROUP, (len(self.left) + 1) // 2)
            self.group = self.left[:half]
        return self.group

    def answer(self, yes):
        """yes=True: the game reacted. None = not sure (try the same group again)."""
        if yes is None or self.group is None:
            return
        self.asked += 1
        g = set(self.group)
        if self.confirming:
            if yes:
                self.found = self.group[0]
            else:
                self.failed = True
        elif yes:
            self.left = [c for c in self.left if c in g]
        else:
            self.left = [c for c in self.left if c not in g]
            if not self.left:
                self.failed = True
        self.group = None

    def status(self):
        if self.found:
            return "found"
        return f"{len(self.left):,} left - about {max(1, len(self.left) - 1).bit_length()} more tries"


# --------------------------------------------------------------------------
# Top-speed finder: the better speed hack. Instead of multiplying the speed the game just worked out,
# find the number it is capped at (max speed) and raise that - the game then goes faster by itself.
# --------------------------------------------------------------------------
class TopSpeedHunt(HumanGroupTest):
    """
    1. You stand still, press ], then run / floor it and keep going. Your speed value levels off at the
       top speed; numbers that equal it (and didn't change) are the candidates.
    2. Still running, the tool doubles half of them for a moment and watches your speed: if it climbs
       way past the old top, the setting is in that half. Halve again - no questions, ~log2(N) rounds.
    """

    FACTORS = (1.0, 1 / 30, 1 / 60, 3.6, 1 / 3.6, 2.23694, 1 / 2.23694)   # same unit, per frame, km/h, mph
    BOOST = 2.0
    RISE = 1.35            # speed must pass old top x this to count

    def __init__(self, speed, top, candidates):
        super().__init__(candidates)
        self.speed = speed               # (addr, type) of the speed value
        self.top = float(top)
        self.rounds = []                 # (group size, peak seen, verdict)

    @staticmethod
    def top_speed(samples):
        s = np.abs(np.array([x for x in samples if x is not None and x == x], dtype=float))
        if not len(s):
            return 0.0
        return float(np.percentile(s, 95))

    @classmethod
    def find_candidates(cls, still, moving, top, speed, tol=0.03, limit=6000):
        """Numbers equal to the top speed (in a few common units) that didn't change while you ran."""
        sp_addr, sp_vt = speed
        types = ["float"] + ([sp_vt] if sp_vt != "float" and top >= 20 else [])   # small whole numbers are everywhere
        found = []
        for vt in types:
            dt = np.dtype(TYPES[vt][0])
            size = TYPES[vt][2]
            n = (min(len(still), len(moving)) // size) * size
            raw_a = still[:n].view(np.dtype(f"u{size}") if size > 1 else np.uint8)
            raw_b = moving[:n].view(np.dtype(f"u{size}") if size > 1 else np.uint8)
            with np.errstate(invalid="ignore", over="ignore"):
                b = moving[:n].view(dt).astype(np.float64)
            same = raw_a == raw_b
            for rank, f in enumerate(cls.FACTORS if vt == "float" else (1.0,)):
                want = top * f
                if want <= 1e-6:
                    continue
                with np.errstate(invalid="ignore", over="ignore"):
                    ok = same & np.isfinite(b) & (np.abs(b - want) <= max(tol * want, 0.0 if vt == "float" else 0.5))
                for i in np.flatnonzero(ok)[:limit]:
                    a = int(i) * size
                    if a < sp_addr + TYPES[sp_vt][2] and sp_addr < a + size:
                        continue                                   # the speed value itself
                    found.append((rank, abs(float(b[i]) - want) / want, a, vt))
        found.sort()
        out, seen = [], set()
        for _, _, a, vt in found:
            if (a, vt) not in seen:
                seen.add((a, vt))
                out.append((a, vt))
            if len(out) >= limit:
                break
        return out

    def boosted(self, value, vt):
        v = value * self.BOOST
        return v if vt == "float" else int(round(v))

    def judge(self, samples):
        """Speeds seen while a group was boosted -> True (it's in there) / False / None (you stopped moving)."""
        s = np.abs(np.array([x for x in samples if x is not None and x == x], dtype=float))
        if len(s) < 3:
            return None
        peak = float(np.max(s[len(s) // 3:]))
        if peak > self.top * self.RISE:
            verdict = True
        elif float(np.median(s)) < 0.6 * self.top:
            verdict = None
        else:
            verdict = False
        self.rounds.append((len(self.group or []), peak, verdict))
        return verdict
