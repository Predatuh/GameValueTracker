# Game Value Tracker - notes for Claude Code

Windows Tk app (Python 3.10+, numpy) that attaches to an emulator / offline PC game, finds values in
memory (AI coach, scanner, recorder), and turns them into cheats, a live mod menu and spawn menus.
The owner (Tanner) uses it on Windows with PCSX2 and RPCS3; he is not a programmer - keep the UI plain-
spoken and do the work for him.

Start with `docs/HANDOFF.md` - the history of how this was built, what's verified on a real PC and
what isn't, and open ideas.

## Files
- `ps2_tracker.py` - the whole GUI (App class, Overlay, MenuOverlay, HELP_TEXT). Thread -> Tk calls
  MUST go through `self.ui(fn, *args)` (queue pumped every 50 ms).
- `ps2core.py` - no GUI. GameTarget (attach: PCSX2/RPCS3/Dolphin/PPSSPP/DuckStation/PC, big-endian
  memory is word-swapped in snapshots; `fa()`/`pa()` show/parse addresses the way each system names
  them), Scanner / MultiScanner, AutoHunter + HitDetector (ball hunt), LaunchPredictor (pitch target),
  effect_test / GroupTester (which value is real), PulseHunter (rise-and-return: jump/run/drive),
  HumanGroupTest (freeze test with YES/NO), analyze_traces / analyze_events (recorder), fingerprint /
  pointer_scan / relocate (values that move), cheat exporters (pnach, Gecko, CWCheat, GameShark, CE),
  code patches for every emulator (`CODE_SYSTEMS`, `code_patch_lines`, RPCS3 patch.yml + log hash),
  TopSpeedHunt (better speed hack: finds the max-speed setting).
- `coach.py` - built-in brain (text -> recipe), recipe validation, Coach runner, prompt for AI brains.
- `brain.py` - Claude / Gemini / OpenAI-compatible chat behind one `Brain.chat()`.
- `gameinfo.py` - game name from emulator window titles, game type, per-genre tabs/examples/events.
- `modmenu.py` - controller (XInput) / keyboard input, MenuEngine, "describe a cheat" parser.
- `spawner.py` - finds ID->name tables in game folders / disc images.
- `menubuilder.py` - "Build my mod menu": one sentence -> menu items (built-in parser or AI) -> MenuBuild
  walks them; the GUI finds each with the coach and hooks in via `_build_hit` / `_build_stuck`.
- `theme.py` - light/dark ttk styling (`apply`, `restyle` for new dialogs, `c("#070")` for the app's fixed
  hint colours). The in-game overlays set `_theme_skip` and keep their own dark look.
- `updater.py` - OTA updates from the GitHub repo (VERSION file + zipball). Bump `VERSION`
  (YYYY.MM.DD.N) and add a CHANGELOG.md entry with every change you push, or users won't get it.
- `GameValueTracker.pyw` - launcher with no console window.

## Tests
`python tests/run_all.py --fast` (no display needed) and `python tests/run_all.py` for everything;
GUI tests need a display (Linux: `xvfb-run -a python tests/run_all.py`). Tests simulate games in
numpy memory - no emulator needed. Keep them passing; add one for every new feature.

## Rules of thumb
- Never write to memory without restoring it in tests/auto-tests; freeze/boost writes stop on answer.
- Online games with anti-cheat are refused on purpose (ps2core ONLINE_EXES / ANTICHEAT_MODULES).
- User-facing text: short, concrete, tells the player exactly what to do next.
