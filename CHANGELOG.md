# What's new

## 2026.10.23.4
- Updates are fast and reliable: the check takes a second instead of a minute, and the download has backup routes when a GitHub server doesn't answer from your PC.
- No more update loop: "Update now" can't be clicked twice, a late check can't cover "Downloading...", and it doesn't restart when there's nothing new.
- A saved GitHub token that no longer works is skipped and forgotten (public repo, no token needed).

## 2026.10.23.3
- Build my mod menu: type the whole menu in one sentence ("infinite ammo on L1+R1, god mode, super speed, spawn a tank"). It finds each value with you and puts every cheat in the in-game menu.
- Better speed hack: "Find top speed" finds the game's own top-speed setting and raises it, so you really go 3x faster. Turning it off puts the normal speed back.
- Code patches now work on RPCS3, Dolphin, PPSSPP and DuckStation too. "Try code patch live" tests one right away, and Export writes it in each emulator's format. RPCS3 patches are added to RPCS3's patch list by themselves.
- New look, with a Dark mode switch at the top right. The AI brain box is always visible now.
- Fixed: the ' key (NO) didn't answer questions in game outside the pitch predictor.

## 2026.10.23.2
- Updates work with a public repo even if an old/wrong GitHub token is still filled in.

## 2026.10.23.1
- Over-the-air updates: the tracker checks your GitHub repo on start and updates itself (Updates... button).
- Searches stop by themselves when another round can't help, then test the leftovers automatically (2-3 actions instead of 20+).
- Overlay questions always show their buttons; answer in game with ] = YES and ' = NO.
- Run / car speed and jumps: do it once per try (rises and comes back). Test-with-me freeze test, speed hack.
- Any AI as the brain: Claude, Gemini, OpenAI-compatible (OpenRouter, Groq, Ollama...).
- Any value type scan, freeze from the Scanner, add to library and name later, values that move get followed.
- Game detection + tabs per game type, per-game libraries, in-game mod menu (L3+R1), spawn menu.
- Works with PCSX2, RPCS3, Dolphin, PPSSPP, DuckStation and offline PC games.
