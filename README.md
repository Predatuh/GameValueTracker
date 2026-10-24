# Game Value Tracker

A Windows tool that attaches to an emulator or a PC game and helps you:

- **AI Coach:** type what you're looking for ("ammo, I have 40", "car speed", "health, I'm full", "ball speed after I hit it"). An overlay on top of the game tells you what to do, and the tool finds the value by itself.
- **Pitch predictor:** finds the spot the CPU picks before it throws (as coordinates or a zone number) and shows it on a strike-zone overlay during the windup. Every pitch counts, hit or not.
- **Find player ratings** (speed, kick power, and so on) for a whole roster and label them.
- **Track live values** while you play, using hotkeys F5–F9 (kick meter, stamina, clock, ball speed).
- **Auto-pinpoint** the right one with the Recorder, which graphs candidates as you play and picks the one that moves like the ball.
- **Keep a library** of everything you found, grouped by category, with live view, edit and freeze.
- **Power boost** multiplies the ball's speed the moment it's hit.
- **Build my mod menu:** type the whole menu in one sentence ("infinite ammo on L1+R1, god mode, super speed, spawn a tank"). The tool finds every value with you, one at a time, and puts each cheat in the in-game menu.
- **Better speed hack:** finds the game's own top-speed setting and raises it, so you aren't held back by the game easing toward its normal top speed.
- **Code patches** (turn off the instruction that, say, takes away ammo) for PS2, PS3, GameCube/Wii, PSP and PS1, with export to each emulator's patch format. RPCS3 patches are added to RPCS3's patch list automatically.
- **Light and dark theme** (the **Dark mode** box at the top right).
- **Mod menu:** describe cheats in plain words ("infinite ammo on L1+R1"), then open an in-game menu with L3 + R1 and switch them on from the controller.
- **Spawn menu:** find the ID of your car, weapon or item, pull the names from the game's files, and spawn anything from the list or the in-game menu.
- **Tailored to each game:** the tool reads the game's name, works out what kind of game it is, shows only the tabs that fit, and keeps a separate library for every game.
- **Export cheat codes** in the right format for each system.

**Supported:**

| System | Emulator | Addresses shown as | Cheat export |
|---|---|---|---|
| PS2 | PCSX2 | `0032A4C0` | `.pnach` |
| PS3 | RPCS3 | `30012340` (PS3 address) | Cheat Engine table, `patch.yml` (code patches) |
| GameCube / Wii | Dolphin | `8034A2C0` | Gecko codes |
| PSP | PPSSPP | `08912340` | CWCheat |
| PS1 | DuckStation | `800C1234` | GameShark |
| PC games | (none) | `gta_sa.exe+76F3B8` | Cheat Engine table |
| Other emulators | Cemu, Xenia, Project64... | as a PC program | Cheat Engine table |

Online games with anti-cheat are blocked; the tool is for emulators and offline / single-player games.

## 1. Install Python (one time)

1. Download Python 3.12 or newer from https://www.python.org/downloads/
2. When the installer opens, **tick "Add python.exe to PATH"**, then click Install Now.
3. Open PowerShell and run:
   ```powershell
   python -m pip install numpy
   ```

## 2. Run it

1. Put all the files in one folder, for example `C:\Users\tanne\Desktop\BassBuilder\ps2tracker`.
2. Double-click **GameValueTracker.pyw** (or **run_tracker.bat**). It opens with no black command window behind it. If it ever crashes, the details are saved in `tracker_errors.log`.
3. Start your emulator and boot the game, or start the PC game.
4. Pick it in the **Game:** list at the top. Emulators are listed first. **System** fills in by itself; change it only if it guessed wrong. For an emulator that isn't listed, pick **Other emulator, big-endian** (PowerPC systems such as Wii U or Xbox 360) or **PC game / any program**.
5. Click **Attach**.

PC game addresses inside the game's exe (`game.exe+offset`) stay the same every time you play. Other PC addresses change each time the game starts, so you'll need to find them again (or use Cheat Engine's pointer scan on the exported table). For PC games, run in windowed or borderless mode so the overlay can show on top.

If attaching fails with an access error, right-click `run_tracker.bat` and choose **Run as administrator**.

## 3. Make an .exe (optional)

Double-click **build_exe.bat**. When it finishes, the app is at `dist\PS2ValueTracker.exe` (the name stays the same). Copy that exe anywhere and it runs without Python. The library file is saved next to it.

## 4. Each game is set up for itself

When you attach, the tool reads the game's name from the emulator's window (PS3, GameCube/Wii and PSP also show the disc ID) and works out the game type: baseball, football, open world, racing, shooter, RPG and so on. It only shows the tabs that fit:

- **Power boost** and **Ratings finder** for sports games
- **Spawn menu** for open-world, racing, shooter and RPG games
- the pitch predictor settings for baseball

If it guesses wrong, change **Game type** at the top; it remembers your choice for that game. Every game has its own library, cheats and spawn lists in the `libraries` folder. If you switch games in the emulator, the tool switches with you. Your old NCAA library moves into NCAA's own file the first time you attach to it.

## 5. Cheats and the in-game mod menu

In **Cheats & mod menu**, type what you want, for example "infinite ammo on L1+R1", "money +10000 on L2+R2", "double car speed on F3" or "set wanted level to 0 with R3". The value has to be saved in the Library first.

- **Keep it at** stays on until you switch it off. With no number, it holds whatever the value is when you turn it on.
- **Set / add / multiply** happen once each time you press the button.

Click **Start mod menu**. In the game, **L3 + R1** (or **Insert**) opens the menu. Use the D-pad (or Numpad 8/2) to move, Cross/A (Numpad 5) to toggle or spawn, and Circle/B (Numpad 0) to go back. Each cheat's own hotkey works any time. Xbox-style controllers work directly; PS4/PS5 controllers work through Steam Input or DS4Windows. For other controllers, find the controller value in memory and click **Learn game pad...**.

**Build the whole menu at once:** at the top of the tab, type something like "infinite ammo on L1+R1, god mode, super speed, moon jump, spawn a tank". Click **Plan it** to see what it understood. With an AI key, the AI plans it and knows the game. Then click **Build it**. The overlay takes you through finding each value, the same way the AI Coach does, and adds each cheat to the menu. Values already in your library are reused. If one won't come out, the overlay offers **Try again**, **Use the best guess** or **Skip this one**.

**Code patches:** click **Add code patch...**, paste the address of the instruction that writes the value (the window tells you how to get it from your emulator's debugger), and keep the NOP it fills in. **Try code patch live** writes it into the running game; click it again to undo. **Export cheats...** makes it stick: `.pnach`, Gecko plus Dolphin patch lines, CWCheat or GameShark. For RPCS3, the tool reads the game's PPU hash from RPCS3's log and adds the patch to RPCS3 itself. In RPCS3, open **Manage > Game Patches**, tick the patch, click **Save** and restart the game.

## 6. Spawn menu

Games keep the ID of the car you're in, the weapon you're holding or the item in a slot. Writing a different ID swaps in something else.

1. Click **Find it with the AI Coach**. Sit in a car (or hold a weapon), switch to a different one when told, and press **]**. Pick the result and click **Use as spawn ID**.
2. Click **Scan game folder...** or **Scan disc image / file...**. The tool lists every ID-to-name table in the game's files. The list containing the IDs you've actually used moves to the top; pick it and click **Use this list**. If the names are packed away, use **Next ID / Prev ID** and **Name this ID...** instead.
3. Click **Spawn selected now**, or add items to the mod menu to spawn them from the controller. Many games only swap the model when you get back in or re-equip.

## 7. Hard-to-find and moving values

- **Not sure of the type?** In the Scanner, pick **any type (all 4)**. Byte, u16, u32 and float are scanned side by side, and each result shows its type.
- **Test by freezing.** Select results and click **Freeze / unfreeze** to hold them while you play, or **Set value...** (double-click) to type a number in.
- **Save now, name later.** **Add to library (name it later)** saves results as "Unnamed 1 (float)" under Unsorted. Rename the right one once you're sure. AI Coach results have the same buttons.
- **Auto-test asks you when it isn't sure.** It writes a number like 77 and asks whether the game shows it. If you answer no, it tests the values right next to it, in every type, until one works.
- **Values that move.** Every saved value remembers what surrounds it in memory. When you attach, the tool finds values that moved and follows them. For values that move while you play (respawns, new levels), click **Moves around: track it** in the Library. The tool then also uses pointers and re-checks every 2 seconds, and gets more reliable each session. Mod menu cheats keep working because they read from the Library.
- **Recorder events fit the game.** Pick what you'll do (shoot twice then reload, take damage then heal, spend money, jump, run then stop, go to lower ground, switch weapon...) and press **]** each time. The recorder tells you the next step and picks the value that followed every one.

## 8. Speed, jumps and "test with me"

For **run speed**, **car speed** or **how high I jump**, you press **]** and do the action once (run for 2 seconds, jump, or floor it), then stop. The tool keeps values that rose and came back the same way every time. Do 4 to 6 tries.

Searches stop by themselves as soon as another round wouldn't help, which happens when what's left all changes together (the real value plus its copies). The tool then tests those itself, starting with the ones that sit apart from the rest, and stops when it finds the one the game really uses. That's usually 2 or 3 actions from you.

When a search ends with too many results, you get three choices:

- **Keep narrowing:** a few more rounds starting from what's left. Pressing **Start** again also continues; **Start over** begins a new search.
- **Test with me:** the tool holds half the candidates still while you try to move (or fire, or whatever changes it). Answer YES if it stopped working. It halves the group each time, so 500 candidates take about 9 questions. Answer with the buttons or with the keys in the game: **]** = YES, **'** = NO.
- **Speed hack test:** the same, but it multiplies the values by 3. Answer YES if you're super fast.

Once it's found, **Speed hack ON/OFF** makes you 3x faster right away, capped at 3x your normal top speed so it can't run away. It's also added to Cheats & mod menu, where you can give it a hotkey or change the multiplier.

**Find top speed (better hack):** select the speed value and click it. Stand still, press **]**, then run (or floor it) and keep going for 30 to 60 seconds. The tool measures your top speed, then looks for the game's own top-speed setting by itself: it doubles groups of numbers that match and watches whether you get faster. After that, **Top speed x3** is on, the game itself lets you go 3x faster, and it exports as a code. Turning it off puts the normal top speed back.

## 9. AI brain (Claude, Gemini, OpenAI, local models)

In the AI Coach tab, pick the brain: **Claude**, **Gemini** (with a key from Google AI Studio), or **OpenAI / OpenAI-compatible**. The OpenAI-compatible option covers OpenRouter, Groq, DeepSeek, xAI, Mistral and Together, plus Ollama or LM Studio running on your PC, which need no key. Paste the key, click **List models**, pick one, then click **Test**. The brain is told which game you're playing. Without a key, the built-in brain works offline.

## 10. AI Coach

1. Open the **AI Coach** tab and type what you want to find, the way you'd say it to a friend.
2. Click **Make a plan** to see the steps, then click **Start**.
3. A small box stays on top of the game and tells you what to do, for example "Speed up for 5 seconds", "Brake now", "Take some damage, then press ]", or "Type your new ammo number". You can drag it anywhere.
4. When it says **Found it!**, the result is in the tool's list. From there you can save it to the library, test it with a new value, or send it to Power boost.

For ball games, type something like "ball speed after I hit it". The tool then runs the fully automatic hunt: you just play and press **]** each time you hit the ball. If you've already saved a ball value, pick it under "auto-detect hits" and you don't need to press anything.

**Predict where the CPU will throw (pitch, shot, pass):** type something like "where is the pitcher going to throw it", or pick **Predict where it will go** in the **I want to:** dropdown.

The game picks the spot *before* the pitcher throws. The predictor looks for that decision in memory; it doesn't guess from where earlier pitches landed.

1. Press **]** the moment the pitcher releases the ball. Swing or take: every pitch counts, hit or not. After about 3 pitches, the tool has found the ball in memory.
2. Keep pressing **]** at each release. For each pitch it notes where the ball crossed the plate (the instant it stops coming toward you, whether it was caught or hit) and what memory looked like during the windup. Then it searches for a value that was already set during the windup and decides the spot. It checks two kinds:
   - **Coordinates:** a number that moves with the location. Usually found in about 6 pitches.
   - **Zone number:** a number such as 0–8, where the same number always means the same spot. It needs each zone to repeat a few times, so this usually takes 8–12 pitches. The tool builds the zone table itself.
3. The overlay turns into a strike zone. During the windup, a dot shows where the pitch is going: green means STRIKE and orange means BALL. If it says "never seen it yet," that zone didn't come up during learning, and it learns it on that pitch.
4. Teach it the zone: after each call, press **;** for a strike or **'** for a ball. Until then the zone is an estimate. You can adjust its size, or flip the view, in the AI Coach tab.

**Export predictor findings** saves a file with every pitch, every value that was set before the windup, and what the tool decided. If it can't find the target, send that file to Claude to dig through.

Each plan starts with **"I UNDERSTOOD: …"**. If that's wrong, change **I want to:** and click **Make a plan** again.

**Auto-test (finds the value that really works):** games keep copies of values, such as the number drawn on the HUD or the ball's render copy. Copies move exactly like the real value but do nothing when you change them. After the coach narrows things down, it tests each result by itself: it changes the value for half a second and watches what the game does.

- **CONTROLS IT:** the game kept the change and the other values followed. Use this one for cheats and boost.
- **COPY:** the game overwrote it immediately, so changing it does nothing.

Ammo, money and health are put back after each test. In ball hunts, testing happens between hits while you keep playing, and the real ball speeds are filled into Power boost automatically. You can also click **Auto-test: which is real?** at any time. Power boost now warns you if the game overwrites a boost, which means the address is a copy.

**Deep test (when every quick test says COPY):** some games rebuild the ball's speed every frame from a hidden value, like hit power, so changing the speed you can see does nothing. The deep test then starts by itself. Right after contact it changes hundreds of values at once and checks whether the ball leaves its normal path. If it does, it splits that group in half and tries again on the next hit, until one value is left. That takes about 10–15 hits for a few thousand values. Everything is put back after every test.

**Code patch (when even the deep test finds nothing):** the game's code is capping or resetting the value, so you change the instruction instead.

1. In PCSX2, open **Debug > Open Debugger**. In the Memory view, go to the value's address, right-click it, and add a write breakpoint. Hit the ball; the game pauses on the instruction that writes the value. Note that instruction's address.
2. In **Cheat/menu maker**, click **Add code patch...**, paste the address, keep `00000000` (a NOP, which skips the instruction), and export. PCSX2 applies pnach patches itself, so the change sticks. Writing code live from the tool doesn't work, because PCSX2 caches compiled code.
3. If the game crashes or acts strangely, you patched the wrong instruction. Remove the patch and try the next write instruction.

**Claude brain (optional):** paste an Anthropic API key in the AI Coach tab and Claude plans the search for anything the built-in brain doesn't recognize. Each plan costs a few cents. Without a key, the built-in brain works offline for ammo, money, lives, score, items, health, armor, stamina, fuel, nitro, speed, height, position, timers, and balls.

The overlay may be hidden if PCSX2 runs in exclusive fullscreen. Use borderless or windowed mode.

## 11. NCAA Football 2006 walkthrough

**Speed and kick power for every player (Ratings finder tab)**

1. In the game, open Rosters → Edit Player and pick any player. Note their ratings.
2. In the tool, type `SPD` and the current speed value. Click **1. Snapshot before**.
3. In the game, raise that player's speed by 1 and confirm. In the tool, type the new value and click **2. Find it**.
4. Repeat if more than one address shows. Then click **Use as Player 1**.
5. Do steps 2–4 for a **different player**, using the same rating (SPD). Click **Use as Player 2**.
6. In Step 2, type both players' ratings as they are now, one per line (`SPD=93`, `ACC=88`, `KPW=75`, `KAC=70`, …). Use the rating abbreviations the game shows.
7. Click **Find roster table**. Check that the preview looks right, then click **Save table to library**.

**Live values while you play (Scanner tab)**

- Kick meter example: set the type to `u32` (try `float` if it doesn't work). Press **F5** right before kicking, **F8** while the meter fills, **F9** after it drops, and **F7** while nothing is happening. Repeat until only a few results are left, then double-click the real one to save it under "Kicking".

**Can't tell which candidate is the ball? (Recorder tab)**

- Send your last few Scanner results to the Recorder. Press **[** to start recording, tap **]** each time the ball is hit, and press **[** again to stop.
- The tool graphs every candidate and picks the one that moves like the ball: height arcs up and down, vertical speed falls steadily, launch speed jumps at contact.
- Once you know the height, use **+ Neighbours** to add the values right next to it. The speed values are usually there.

**Crush the ball (Power boost tab)**

- Pick the ball's velocity values, set **Multiply by** (for example 3), and click **Start boost**, or press the **backslash** key in game. Every hit gets multiplied the moment the bat makes contact. Pitches and bounces are left alone.
- To test an address: pause mid-flight, click **Boost now (test)**, and unpause. If the ball shoots off faster, it's a velocity. If it teleports, it's a position.

**Cheats (Cheat / menu maker tab)**

- Add a cheat, for example "All players 99 speed": target `Player ratings › SPD`, all players, value 99.
- Export the file. Its name must be the game's CRC, which PCSX2 shows in the game's Properties or in its log, for example `1A2B3C4D.pnach`. Save it in PCSX2's `cheats` folder.
- In PCSX2, right-click the game → Properties → Cheats, and tick the cheats you want.

## Limits

- Nothing can label memory by itself. You tell the tool what a value is once, and then it's saved.
- Some games store ratings compressed or in a different form, so the exact-value search can miss them. If that happens, use the Scanner with "changed / increased" while editing the rating.
- The button activator uses PCSX2's `E` conditional code type. If a combo cheat doesn't trigger, check that the controller value you saved is the right one.
- Live values such as the kick meter can move in memory between plays or games. If a saved address stops working, find it again.
