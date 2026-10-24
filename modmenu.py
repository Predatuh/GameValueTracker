"""
modmenu.py - the in-game mod menu: controller / keyboard hotkeys, a menu you open with a button
combo (default L3 + R1), cheats that freeze / set / add / multiply, and spawn items.

Pure logic lives in MenuEngine so it can be tested without a game or a controller.
"""
import ctypes
import os
import re

IS_WIN = os.name == "nt"

# PlayStation names for buttons. Xbox-style pads (and DS4/DualSense through Steam / DS4Windows)
# report the same buttons through XInput.
BUTTONS = ["Up", "Down", "Left", "Right", "Start", "Select", "L3", "R3", "L1", "R1",
           "Cross", "Circle", "Square", "Triangle", "L2", "R2"]
XINPUT_BITS = {"Up": 0x0001, "Down": 0x0002, "Left": 0x0004, "Right": 0x0008, "Start": 0x0010,
               "Select": 0x0020, "L3": 0x0040, "R3": 0x0080, "L1": 0x0100, "R1": 0x0200,
               "Cross": 0x1000, "Circle": 0x2000, "Square": 0x4000, "Triangle": 0x8000}
ALIASES = {"x": "Cross", "cross": "Cross", "a": "Cross", "circle": "Circle", "o": "Circle", "b": "Circle",
           "square": "Square", "triangle": "Triangle", "y": "Triangle", "l1": "L1", "lb": "L1",
           "r1": "R1", "rb": "R1", "l2": "L2", "lt": "L2", "r2": "R2", "rt": "R2", "l3": "L3", "ls": "L3",
           "r3": "R3", "rs": "R3", "start": "Start", "select": "Select", "back": "Select", "up": "Up",
           "down": "Down", "left": "Left", "right": "Right", "dpad up": "Up", "dpad down": "Down",
           "dpad left": "Left", "dpad right": "Right"}

# keyboard keys people can use as hotkeys: name -> virtual-key code
KEYS = {**{f"F{i}": 0x6F + i for i in range(1, 13)},
        **{f"Num{i}": 0x60 + i for i in range(10)},
        **{chr(c): c for c in range(ord("A"), ord("Z") + 1)},
        **{str(i): 0x30 + i for i in range(10)},
        "Insert": 0x2D, "Delete": 0x2E, "Home": 0x24, "End": 0x23, "PageUp": 0x21, "PageDown": 0x22,
        "ArrowUp": 0x26, "ArrowDown": 0x28, "ArrowLeft": 0x25, "ArrowRight": 0x27, "Enter": 0x0D,
        "Backspace": 0x08, "Ctrl": 0x11, "Shift": 0x10, "Alt": 0x12, "Tab": 0x09,
        "Num+": 0x6B, "Num-": 0x6D, "Num*": 0x6A, "Num/": 0x6F}

DEFAULT_MENU = {"open": ["L3", "R1"], "up": ["Up"], "down": ["Down"], "select": ["Cross"],
                "back": ["Circle"], "kb_open": ["Insert"], "kb_up": ["Num8"], "kb_down": ["Num2"],
                "kb_select": ["Num5"], "kb_back": ["Num0"]}
MODES = {"freeze": "keep it at", "scale": "keep it multiplied by", "set": "set to", "add": "add",
         "multiply": "multiply by"}
TOGGLE_MODES = ("freeze", "scale")


def combo_text(combo):
    return " + ".join(combo) if combo else "-"


def parse_combo(text):
    """'L3 + R1', 'l1+r1+x', 'F2', 'Num5' -> ['L3', 'R1'] ..."""
    out = []
    for part in re.split(r"\s*\+\s*|\s*,\s*|\s+and\s+", (text or "").strip()):
        p = part.strip()
        if not p:
            continue
        low = p.lower()
        if low in ALIASES:
            out.append(ALIASES[low])
        elif low.startswith("numpad"):
            out.append("Num" + p[6:].strip())
        else:
            k = next((k for k in KEYS if k.lower() == low), None)
            if k is None:
                raise ValueError(f"Don't know the button/key '{p}'")
            out.append(k)
    return out


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------
class XInputPad:
    """First connected XInput controller."""

    class STATE(ctypes.Structure):
        _fields_ = [("dwPacketNumber", ctypes.c_uint32), ("wButtons", ctypes.c_uint16),
                    ("bLeftTrigger", ctypes.c_uint8), ("bRightTrigger", ctypes.c_uint8),
                    ("sThumbLX", ctypes.c_int16), ("sThumbLY", ctypes.c_int16),
                    ("sThumbRX", ctypes.c_int16), ("sThumbRY", ctypes.c_int16)]

    def __init__(self):
        self.dll = None
        if IS_WIN:
            for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
                try:
                    self.dll = ctypes.WinDLL(name)
                    break
                except OSError:
                    pass
        self.index = 0

    @property
    def available(self):
        return self.dll is not None

    def pressed(self):
        if not self.dll:
            return set()
        st = self.STATE()
        for i in [self.index] + [j for j in range(4) if j != self.index]:
            if self.dll.XInputGetState(i, ctypes.byref(st)) == 0:
                self.index = i
                out = {n for n, b in XINPUT_BITS.items() if st.wButtons & b}
                if st.bLeftTrigger > 60:
                    out.add("L2")
                if st.bRightTrigger > 60:
                    out.add("R2")
                return out
        return set()


class Keyboard:
    def __init__(self):
        self.u32 = ctypes.windll.user32 if IS_WIN else None

    def pressed(self, names=None):
        if not self.u32:
            return set()
        return {n for n in (names or KEYS) if self.u32.GetAsyncKeyState(KEYS[n]) & 0x8000}


def mem_pad_pressed(raw, mapping):
    """A controller value found in game memory. mapping: {button: (mask, pressed_when_zero)}."""
    out = set()
    for name, (mask, active_low) in mapping.items():
        bit = raw & mask
        if (bit == 0) if active_low else (bit != 0):
            out.add(name)
    return out


def learn_pad_mapping(idle, samples):
    """
    idle: raw controller value with nothing held. samples: {button: raw value while held}.
    Works for PS2-style pads (bit goes 0 when pressed) and normal ones (bit goes 1).
    """
    m = {}
    for name, raw in samples.items():
        diff = idle ^ raw
        if diff and diff & (diff - 1) == 0:          # exactly one bit changed
            m[name] = (diff, bool(idle & diff))
    return m


# --------------------------------------------------------------------------
# Menu engine
# --------------------------------------------------------------------------
class MenuEngine:
    """
    items: cheats [{'name', 'mode', 'value', 'hotkey': [...], 'group', ...}]. The app supplies
    write(cheat, on) to apply them. tick(buttons, keys) returns events for the overlay.
    """

    def __init__(self, cheats, keys=None):
        self.keys = dict(DEFAULT_MENU, **(keys or {}))
        self.cheats = cheats
        self.open = False
        self.group = None             # None = list of groups
        self.cursor = 0
        self.prev = set()
        self.events = []

    # -- what the overlay shows --
    def groups(self):
        out = []
        for c in self.cheats:
            g = c.get("group") or "Cheats"
            if g not in out:
                out.append(g)
        return out

    def rows(self):
        if self.group is None:
            gs = self.groups()
            if len(gs) == 1:
                self.group = gs[0]
            else:
                return [(g + "  >", None) for g in gs]
        return [(c["name"], c) for c in self.cheats if (c.get("group") or "Cheats") == self.group]

    def title(self):
        return "MOD MENU" if self.group is None else self.group.upper()

    # -- input --
    def _hit(self, held, combo):
        """combo just completed this tick (all held now, not all held before)."""
        return bool(combo) and set(combo) <= held and not set(combo) <= self.prev

    def tick(self, held):
        """held: set of button and key names down right now. Returns [(event, cheat or text)]."""
        ev = []
        k = self.keys
        if self._hit(held, k["open"]) or self._hit(held, k["kb_open"]):
            self.open = not self.open
            self.group, self.cursor = None, 0
            ev.append(("menu", self.open))
        elif self.open:
            rows = self.rows()
            if self._hit(held, k["up"]) or self._hit(held, k["kb_up"]):
                self.cursor = (self.cursor - 1) % max(1, len(rows))
                ev.append(("move", self.cursor))
            elif self._hit(held, k["down"]) or self._hit(held, k["kb_down"]):
                self.cursor = (self.cursor + 1) % max(1, len(rows))
                ev.append(("move", self.cursor))
            elif self._hit(held, k["select"]) or self._hit(held, k["kb_select"]):
                if rows:
                    label, c = rows[min(self.cursor, len(rows) - 1)]
                    if c is None:
                        self.group, self.cursor = label[:-3], 0
                        ev.append(("move", 0))
                    else:
                        ev.append(self.activate(c))
            elif self._hit(held, k["back"]) or self._hit(held, k["kb_back"]):
                if self.group is not None and len(self.groups()) > 1:
                    self.group, self.cursor = None, 0
                    ev.append(("move", 0))
                else:
                    self.open = False
                    ev.append(("menu", False))
        # direct hotkeys work with the menu open or closed (but not the menu's own buttons while open)
        nav = set().union(*[set(v) for kk, v in k.items() if kk != "open" and kk != "kb_open"]) if self.open else set()
        for c in self.cheats:
            hk = c.get("hotkey")
            if hk and self._hit(held, hk) and not (self.open and set(hk) <= nav):
                ev.append(self.activate(c))
        self.prev = set(held)
        return ev

    @staticmethod
    def activate(c):
        if c.get("mode", "freeze") in TOGGLE_MODES:
            c["on"] = not c.get("on")
            return ("toggle", c)
        return ("fire", c)

    def frozen(self):
        return [c for c in self.cheats if c.get("mode", "freeze") in TOGGLE_MODES and c.get("on")]


def apply_value(mode, current, value):
    """New value for one-shot modes."""
    if mode == "add":
        return current + value
    if mode == "multiply":
        return current * value
    return value


# --------------------------------------------------------------------------
# "Describe a cheat" - built-in parser (Claude can do it too)
# --------------------------------------------------------------------------
INF_WORDS = ("infinite", "unlimited", "inf ", "never run out", "god mode", "freeze", "lock", "always",
             "max", "full")
BUTTON_WORDS = r"(?:l1|l2|l3|r1|r2|r3|x|cross|circle|square|triangle|start|select|up|down|left|right|" \
               r"lb|rb|lt|rt|ls|rs|f\d{1,2}|num\s?\d|numpad\s?\d|insert|home|end|delete|page ?up|page ?down)"


def split_hotkey(text):
    """'infinite ammo on L1+R1' -> (['L1', 'R1'], ' infinite ammo ') - lower-cased text without the hotkey."""
    t = " " + text.lower().strip() + " "
    hotkey = []
    m = re.search(r"(?:on|with|when i (?:press|hold)|press|hold|hotkey|using)\s+(" + BUTTON_WORDS +
                  r"(?:\s*(?:\+|and|,)\s*" + BUTTON_WORDS + r")*)\s", t)
    if m:
        hotkey = parse_combo(m.group(1).replace("page up", "PageUp").replace("page down", "PageDown")
                             .replace("num ", "num"))
        t = t.replace(m.group(0), " ")
    return hotkey, t


def describe_cheat(text, names):
    """
    'infinite ammo on L1+R1', 'money +10000 when I press L2 + R2', 'double speed', 'health 999',
    'set wanted level to 0 with F3'. names = library value names. Returns a cheat dict or raises.
    """
    hotkey, t = split_hotkey(text)
    best, score = None, 0
    for n in names:
        words = [w for w in re.split(r"[^a-z0-9]+", n.lower()) if len(w) > 2]
        s = sum(1 for w in words if w in t) / max(1, len(words))
        if n.lower() in t:
            s += 1
        if s > score:
            best, score = n, s
    if not best:
        raise ValueError("Which value? Save it to the library first (AI Coach -> Save to library), "
                         "then use its name.")
    mode, value = mode_and_value(t, best)
    return {"name": pretty_name(text, best), "entry": best, "mode": mode,
            "value": value, "hotkey": hotkey, "activator": None, "group": "Cheats"}


def mode_and_value(t, about=""):
    """What a description wants done: ('freeze' | 'scale' | 'set' | 'add' | 'multiply', value or None)."""
    num = re.search(r"([+-]?\d+(?:\.\d+)?)", t)
    value = float(num.group(1)) if num else None
    if re.search(r"\b(double|x2|2x)\b", t):
        mode, value = "multiply", 2.0
    elif re.search(r"\b(triple|x3|3x)\b", t):
        mode, value = "multiply", 3.0
    elif re.search(r"\b(half|halve)\b", t):
        mode, value = "multiply", 0.5
    elif re.search(r"\b(times|multiply|x)\s*\d", t):
        mode = "multiply"
    elif re.search(r"(\+\s*\d|\badd\b|\bgive\b|\bget\b|\bmore\b)", t) and value is not None:
        mode, value = "add", abs(value)
    elif any(w in t for w in INF_WORDS) or value is None:
        mode = "freeze"
    elif re.search(r"\bset\b|\bto\b|\bmake\b", t):
        mode = "set" if not any(w in t for w in INF_WORDS) else "freeze"
    else:
        mode = "freeze"
    speedy = re.search(r"(speed|velocity|fast|sprint|run|jump|gravity|power)", about.lower() + " " + t)
    if mode == "multiply" and speedy:
        mode = "scale"                  # speed hacks must keep multiplying - the game recalculates speed
    elif re.search(r"\b(super ?fast|speed ?hack|faster|fast)\b", t) and speedy and mode in ("freeze", "set"):
        mode, value = "scale", (value if value and value > 1 else 3.0)
    return mode, value


def pretty_name(text, fallback=""):
    """The description without its hotkey, capitalised - the cheat's name."""
    pretty = re.sub(r"\s+", " ", text.strip())
    pretty = re.sub(r"(?i)\s*(on|with|when i press|when i hold|press|hold)\s+" + BUTTON_WORDS +
                    r"(\s*(\+|and|,)\s*" + BUTTON_WORDS + r")*\s*$", "", pretty).strip() or fallback
    return pretty[:1].upper() + pretty[1:]
