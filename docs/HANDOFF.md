# Handoff: how this project got here (from the claude.ai chat, Oct 22-23 2026)

Read this before changing anything. It's the condensed history of the chat this app was built in.

## Who it's for
Tanner - not a programmer. Learning reverse engineering to make cheats and mod menus for old games.
Plays on Windows with PCSX2 2.8.2 (NCAA Football 2006, MLB / baseball, GTA) and RPCS3 (Mercenaries 2:
World in Flames, BLUS30056). Wants everything automatic ("AI does it, I just play"), plain words, and
results in very few in-game actions. Runs the app with GameValueTracker.pyw (no console window).
Brain: Claude by default; he wants to try Google Gemini too (brain.py supports it).

## How it evolved (each step was a complaint that got fixed)
1. PS2 value tracker for NCAA 2006 ratings -> edited values reverted -> copies/mirrors + freeze.
2. "Speed / power hack": Power boost multiplies ball velocity at contact (Booster).
3. "AI watcher": AI Coach turns plain text into scan steps; overlay tells the player what to do.
4. "Find the REAL value, not copies": effect_test (write -> did it stick, did copies follow).
5. Copies everywhere: deep test (change hundreds at once, halve) -> found hidden hit power.
6. Pitch predictor: reads the CPU's pre-chosen target (coordinates or zone number) before release;
   every pitch counts, hit or not.
7. Any emulator / PC game: GameTarget with per-system attach, big-endian word swap, fa()/pa().
8. Tailored per game: detect title from window, genre -> tabs/examples/recorder events; per-game
   library files; mod menu (L3+R1, XInput/keyboard); spawn menu (ID swap + names from game files).
9. Moving addresses: fingerprint + pointer paths, relocate on attach, live tracking.
10. "20+ steps is too many": stop when a round doesn't shrink the list (copies), auto-test the rest
    (loners first, stop at first CONTROLS); merge "do X, press ]" into the scan step; pulse hunts for
    jump/run/drive (rise and return); "Test with me" freeze binary search with ] = YES, ' = NO.
11. OTA updates from this repo (updater.py): bump VERSION + CHANGELOG.md on every push.
12. (Claude Code, Oct 23) "Build my mod menu" from one sentence (menubuilder.py), top-speed finder
    (TopSpeedHunt - raises the game's max-speed setting instead of scaling current speed), code patches
    for RPCS3/Dolphin/PPSSPP/DuckStation (live try + export; RPCS3 patch.yml installed into
    patches/imported_patch.yml using the PPU hash from RPCS3.log), new flat look + dark mode (theme.py).
    Fixed: ' (NO) never reached YES/NO questions outside the predictor.

## Verified vs NOT verified
- Everything is tested against simulated games in numpy memory (tests/). All pass.
- NOT verified on a real PC: Windows attach code for RPCS3 (fixed base 0x300000000 - works in his
  screenshots), Dolphin (MEM1 region search), PPSSPP (window-message base pointer - least sure),
  DuckStation (RAM export); XInput controller reading; reading game names from window titles
  (RPCS3 title format confirmed from a screenshot); PC-game pointer sizes; spawn file scanning on real
  disc images. When he reports a problem with these, they're the first suspects.
- Also NOT verified on a real PC (new): RPCS3.log line formats (PPU hash / Serial / APP_VER regexes in
  rpcs3_log_info) and whether RPCS3 picks up our appended imported_patch.yml; live code patches on
  any emulator (recompilers cache code - Dolphin/PCSX2/RPCS3 likely ignore them, hence export);
  the top-speed finder on a real game; how the new theme looks at his DPI scaling.
- Real-world confirmed by him: PCSX2 attach, coach + auto-test finding ammo on RPCS3 (u16 33DC3DA0 in
  Mercenaries 2 was the real ammo; the u32 30D7Cxxx values were HUD copies).

## Open ideas / not done
- Code patches still need the instruction address from the emulator's debugger (RPCS3 has no write
  breakpoints - Ghidra / patch guides). Finding "what writes this value" automatically isn't done.
- Top-speed finder only knows numbers equal to the measured top speed (a few unit factors); games
  that compute the cap (e.g. from a stat) won't have one - the old scale hack is the fallback.
- Spawning only swaps the ID of what you already have; true spawning needs calling game code.
- The .exe build can't self-update; the .pyw launcher can.

## Working with him
- He sends screenshots of what went wrong. Look at the exact on-screen text and fix that path.
- Keep every overlay instruction short and do-able in game; answers via ] / ' keys work in game.
- Ship: run tests (`python tests/run_all.py`), bump VERSION (YYYY.MM.DD.N), add CHANGELOG entry,
  commit, push to main - he gets it through the in-app "Update ready" bar.
