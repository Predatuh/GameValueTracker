"""
theme.py - the look: a clean flat style with a light and a dark theme (switch in the top bar).

apply(root, "dark" | "light") styles every ttk widget, recolours plain Tk widgets (text boxes,
lists, the plot) and swaps the hard-coded hint colours used around the app for ones that read well
on the current background. c("#070") gives the themed version of one of those colours.
"""
import tkinter as tk
from tkinter import ttk

PALETTES = {
    "light": {
        "bg": "#f3f4f6", "surface": "#ffffff", "surface2": "#e5e7eb", "border": "#d1d5db",
        "text": "#111827", "muted": "#6b7280", "info": "#1e3a8a", "accent": "#2563eb",
        "accent_hover": "#1d4ed8", "accent_text": "#ffffff", "select": "#dbeafe", "select_text": "#111827",
        "ok": "#15803d", "warn": "#b45309", "danger": "#b91c1c", "warn_bg": "#fef3c7", "best": "#d8f5d0",
        "header": "#111827", "header_text": "#f9fafb", "header_muted": "#9ca3af", "button": "#e5e7eb",
        "button_hover": "#d1d5db", "field": "#ffffff", "plot": "#ffffff",
    },
    "dark": {
        "bg": "#111318", "surface": "#1a1d24", "surface2": "#242833", "border": "#323846",
        "text": "#e5e7eb", "muted": "#9ca3af", "info": "#93c5fd", "accent": "#3b82f6",
        "accent_hover": "#2563eb", "accent_text": "#ffffff", "select": "#1e3a8a", "select_text": "#f9fafb",
        "ok": "#4ade80", "warn": "#fbbf24", "danger": "#f87171", "warn_bg": "#422006", "best": "#14532d",
        "header": "#0b0d11", "header_text": "#f9fafb", "header_muted": "#9ca3af", "button": "#2a2f3a",
        "button_hover": "#353b48", "field": "#0f1116", "plot": "#0f1116",
    },
}
# colours written straight into the app's widgets -> which theme colour they stand for
ROLES = {"#666": "muted", "#444": "muted", "#6b7280": "muted", "#335": "info", "#1d4ed8": "info",
         "#b00": "danger", "#070": "ok", "#080": "ok", "#000": "text", "#b45309": "warn",
         "#fef3c7": "warn_bg", "#f7f7f7": "surface", "white": "plot", "#d8f5d0": "best", "#e5e7eb": "button"}
FONT = ("Segoe UI", 10)

_mode = "light"


def mode():
    return _mode


def pal():
    return PALETTES[_mode]


def c(color):
    """Themed version of one of the app's fixed colours (anything unknown comes back unchanged)."""
    role = ROLES.get(str(color).lower())
    return pal()[role] if role else color


def apply(root, new_mode=None):
    global _mode
    if new_mode in PALETTES:
        _mode = new_mode
    p = pal()
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    root.configure(background=p["bg"])
    st.configure(".", background=p["bg"], foreground=p["text"], fieldbackground=p["field"],
                 bordercolor=p["border"], lightcolor=p["bg"], darkcolor=p["bg"], troughcolor=p["surface2"],
                 selectbackground=p["select"], selectforeground=p["select_text"], insertcolor=p["text"],
                 focuscolor=p["accent"], font=FONT)
    st.map(".", foreground=[("disabled", p["muted"])])
    st.configure("TFrame", background=p["bg"])
    st.configure("Card.TFrame", background=p["surface"])
    st.configure("TLabel", background=p["bg"], foreground=p["text"])
    st.configure("Muted.TLabel", foreground=p["muted"])
    st.configure("Title.TLabel", font=("Segoe UI", 12, "bold"))
    st.configure("Header.TFrame", background=p["header"])
    st.configure("Header.TLabel", background=p["header"], foreground=p["header_text"],
                 font=("Segoe UI Semibold", 13))
    st.configure("HeaderMuted.TLabel", background=p["header"], foreground=p["header_muted"], font=("Segoe UI", 9))
    st.configure("Status.TLabel", background=p["surface2"], foreground=p["text"], padding=(10, 4))
    st.configure("TButton", background=p["button"], foreground=p["text"], bordercolor=p["border"],
                 lightcolor=p["button"], darkcolor=p["button"], padding=(10, 4), relief="flat",
                 focusthickness=1)
    st.map("TButton", background=[("pressed", p["button_hover"]), ("active", p["button_hover"])],
           lightcolor=[("active", p["button_hover"])], darkcolor=[("active", p["button_hover"])])
    st.configure("Small.TButton", padding=(6, 2), font=("Segoe UI", 9))
    st.configure("Accent.TButton", background=p["accent"], foreground=p["accent_text"],
                 lightcolor=p["accent"], darkcolor=p["accent"], bordercolor=p["accent"],
                 font=("Segoe UI Semibold", 10))
    st.map("Accent.TButton", background=[("pressed", p["accent_hover"]), ("active", p["accent_hover"])],
           lightcolor=[("active", p["accent_hover"])], darkcolor=[("active", p["accent_hover"])],
           foreground=[("disabled", p["muted"])])
    st.configure("Header.TButton", background=p["header"], foreground=p["header_text"], bordercolor=p["header"],
                 lightcolor=p["header"], darkcolor=p["header"], padding=(8, 3))
    st.map("Header.TButton", background=[("active", p["surface2"])], foreground=[("active", p["text"])])
    for w in ("TEntry", "TCombobox", "TSpinbox"):
        st.configure(w, fieldbackground=p["field"], foreground=p["text"], background=p["surface2"],
                     bordercolor=p["border"], lightcolor=p["field"], darkcolor=p["field"],
                     arrowcolor=p["text"], insertcolor=p["text"], padding=(6, 3))
        st.map(w, fieldbackground=[("readonly", p["field"]), ("disabled", p["surface2"])],
               foreground=[("readonly", p["text"]), ("disabled", p["muted"])],
               bordercolor=[("focus", p["accent"])], lightcolor=[("focus", p["accent"])],
               selectbackground=[("readonly", p["field"])], selectforeground=[("readonly", p["text"])])
    st.configure("TCheckbutton", background=p["bg"], foreground=p["text"], indicatorbackground=p["field"],
                 indicatorforeground=p["accent"])
    st.map("TCheckbutton", background=[("active", p["bg"])],
           indicatorbackground=[("selected", p["accent"]), ("active", p["surface2"])])
    st.configure("Header.TCheckbutton", background=p["header"], foreground=p["header_text"],
                 indicatorbackground=p["surface2"])
    st.map("Header.TCheckbutton", background=[("active", p["header"])],
           indicatorbackground=[("selected", p["accent"])])
    st.configure("TRadiobutton", background=p["bg"], foreground=p["text"])
    st.configure("TNotebook", background=p["bg"], bordercolor=p["border"], tabmargins=(4, 6, 4, 0),
                 lightcolor=p["bg"], darkcolor=p["bg"])
    st.configure("TNotebook.Tab", background=p["bg"], foreground=p["muted"], padding=(12, 6),
                 bordercolor=p["bg"], lightcolor=p["bg"], darkcolor=p["bg"], font=("Segoe UI", 10))
    st.map("TNotebook.Tab", background=[("selected", p["surface"]), ("active", p["surface2"])],
           foreground=[("selected", p["text"]), ("active", p["text"])],
           lightcolor=[("selected", p["accent"])], bordercolor=[("selected", p["border"])])
    st.configure("TLabelframe", background=p["bg"], bordercolor=p["border"], lightcolor=p["bg"],
                 darkcolor=p["bg"], relief="solid", borderwidth=1)
    st.configure("TLabelframe.Label", background=p["bg"], foreground=p["info"], font=("Segoe UI Semibold", 10))
    st.configure("Treeview", background=p["surface"], fieldbackground=p["surface"], foreground=p["text"],
                 bordercolor=p["border"], lightcolor=p["surface"], darkcolor=p["surface"], rowheight=26)
    st.map("Treeview", background=[("selected", p["select"])], foreground=[("selected", p["select_text"])])
    st.configure("Treeview.Heading", background=p["surface2"], foreground=p["text"], bordercolor=p["border"],
                 lightcolor=p["surface2"], darkcolor=p["surface2"], relief="flat", padding=(6, 5),
                 font=("Segoe UI Semibold", 9))
    st.map("Treeview.Heading", background=[("active", p["button_hover"])])
    st.configure("Vertical.TScrollbar", background=p["surface2"], troughcolor=p["bg"], bordercolor=p["bg"],
                 arrowcolor=p["muted"], lightcolor=p["surface2"], darkcolor=p["surface2"])
    st.configure("Horizontal.TScrollbar", background=p["surface2"], troughcolor=p["bg"], bordercolor=p["bg"],
                 arrowcolor=p["muted"], lightcolor=p["surface2"], darkcolor=p["surface2"])
    st.map("Vertical.TScrollbar", background=[("active", p["button_hover"])])
    st.configure("TSeparator", background=p["border"])
    st.configure("TProgressbar", background=p["accent"], troughcolor=p["surface2"])
    # the drop-down list of a combobox is a plain Tk listbox
    root.option_add("*TCombobox*Listbox.background", p["field"])
    root.option_add("*TCombobox*Listbox.foreground", p["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", p["accent_text"])
    root.option_add("*Toplevel.background", p["bg"])
    restyle(root)
    dark_titlebar(root)


def _role_of(w, opt):
    """Remember which theme colour a widget's fixed colour stood for (so switching back works)."""
    key = "_theme_" + opt
    role = getattr(w, key, None)
    if role is None:
        try:
            val = str(w.cget(opt))
        except (tk.TclError, AttributeError):
            return None
        role = ROLES.get(val.lower(), "")
        if not role:
            for r, col in PALETTES["light"].items():       # already themed once
                if col == val.lower() or PALETTES["dark"][r] == val.lower():
                    role = r
                    break
        try:
            setattr(w, key, role)
        except AttributeError:
            return None
    return role or None


def restyle(widget):
    """Recolour plain Tk widgets and fixed hint colours under `widget` (call it for new dialogs too)."""
    p = pal()
    stack = [widget]
    while stack:
        w = stack.pop()
        if getattr(w, "_theme_skip", False):         # the overlays keep their own dark look
            continue
        stack.extend(w.winfo_children())
        cls = w.winfo_class()
        try:
            if cls in ("Text", "Listbox"):
                bg = _role_of(w, "background")
                w.configure(background=p.get(bg if bg in ("surface", "plot") else "surface", p["surface"]),
                            foreground=p["text"], selectbackground=p["select"], selectforeground=p["select_text"],
                            highlightthickness=1, highlightbackground=p["border"], highlightcolor=p["accent"],
                            relief="flat", borderwidth=0)
                if cls == "Text":
                    w.configure(insertbackground=p["text"], padx=8, pady=6)
            elif cls == "Canvas" and not getattr(w, "_theme_keep", False):
                w.configure(background=p["plot"])
            elif cls == "Toplevel":
                w.configure(background=p["bg"])
            elif cls in ("Frame", "Label", "Button"):
                bg = _role_of(w, "background")
                if bg:
                    w.configure(background=p[bg])
                    if cls != "Frame":
                        w.configure(foreground=p["text"] if bg != "ok" else "#000000")
            elif cls in ("TLabel", "TCheckbutton"):
                fg = _role_of(w, "foreground")
                if fg:
                    w.configure(foreground=p[fg])
        except tk.TclError:
            pass


def dark_titlebar(root):
    """Windows 10/11: dark window title bar in dark mode."""
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        val = ctypes.c_int(1 if _mode == "dark" else 0)
        for attr in (20, 19):                      # DWMWA_USE_IMMERSIVE_DARK_MODE (new, old builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass
