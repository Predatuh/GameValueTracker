"""Double-click this to start Game Value Tracker with no black command window."""
import os
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)


def _msg(text):
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("Game Value Tracker", text)
        r.destroy()
    except Exception:
        pass


try:
    import numpy  # noqa: F401
except ImportError:
    exe = sys.executable.replace("pythonw.exe", "python.exe")
    subprocess.call([exe, "-m", "pip", "install", "numpy"], creationflags=0x08000000)   # no window
    try:
        import numpy  # noqa: F401
    except ImportError:
        _msg("numpy isn't installed and couldn't be installed automatically.\n\n"
             "Open PowerShell and run:  python -m pip install numpy")
        sys.exit(1)

try:
    import ps2_tracker
    ps2_tracker.main()
except Exception:
    log = os.path.join(HERE, "tracker_errors.log")
    with open(log, "a", encoding="utf-8") as f:
        f.write(traceback.format_exc() + "\n")
    _msg(f"Game Value Tracker crashed. Details were saved to:\n{log}")
