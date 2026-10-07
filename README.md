# CouchDoom

Fullscreen gamepad launcher for [DoomRunner](https://github.com/Youda008/DoomRunner) presets. It reads DoomRunner's `options.json` and launches the engine with the same IWAD, mods, map packs and arguments. It never writes to `options.json`; keep editing presets in DoomRunner itself.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip install --no-deps tinysoundfont
```

Uses `pygame-ce` (imports as `pygame`), which ships wheels for current Python versions. `tinysoundfont` renders MIDI title music; install it with `--no-deps` because its optional live-playback dependency (PyAudio) has no wheel for new Pythons and isn't used here. Without it, MIDI title tracks are skipped and everything else works.

## Run

| Command | What it does |
| --- | --- |
| `.\run.bat` | Fullscreen, with console output |
| `.\run.bat --windowed` | Windowed, with console output |
| `.\run.bat --dry-run [--preset text]` | Print the launch command for each preset and exit |

For the couch, launch it without a console from a shortcut or a `.bat` anywhere (for example next to DoomRunner):

```bat
@echo off
set "COUCH=C:\path\to\couch-doom"
set "PYTHONPATH=%COUCH%\src"
start "" "%COUCH%\.venv\Scripts\pythonw.exe" -m couch_doom %*
```

Options file: `--options <path>` or the `DOOMRUNNER_OPTIONS` env var if set. Otherwise the first one that exists of `D:\Standalone\UZDoom\DoomRunner\options.json` (portable install), `%LOCALAPPDATA%\DoomRunner\options.json`, then `%APPDATA%\DoomRunner\options.json`.

If the file is missing, can't be parsed, or has no presets, the launcher opens on a notice explaining what's wrong and listing the paths it tried, instead of closing. Press A / Enter to reload once it's fixed (for example after saving a preset in DoomRunner); B / Esc quits. The problem is also written to the log, and `--dry-run` prints it and exits with code 2 (or 1 when there are no presets).

## Controls

| Pad | Keyboard | List | Search keyboard |
| --- | --- | --- | --- |
| D-pad / left stick | Arrows | Move (hold to repeat) | Move key |
| A / Start | Enter | Play | Type key (Start plays) |
| X | Tab | Info sheet (Readme / Command / ENDOOM tabs) | Delete |
| Y | `/` or just type | Open search | Done |
| R3 (click right stick) | F3 | Add to / remove from Favorites | |
| Back / View | F2 | Title music on/off (remembered) | |
| B | Esc | Clear filter, else quit (press twice) | Cancel and clear |
| LB / RB, D-pad left/right | Left / Right | Previous / next section | |
| LT / RT | PgUp / PgDn | Jump 8 presets | |

In the info sheet: LB/RB or Left/Right switch tabs (each tab keeps its scroll position until the sheet closes), right stick or Up/Down scroll, LT/RT or PgUp/PgDn page, A/Start/Enter plays, B/Esc closes.

Favorites get their own section at the top of the list (they stay in their own section too, marked with a star), and the launcher opens on them: on the last-played one if it's a favorite, otherwise on the first.

The launcher window closes while the game runs and comes back when the engine exits. If the engine exits with an error within 15 seconds, the exit code is shown.

## Title music, readmes and sounds

Nothing here depends on a particular engine; it all comes from the preset's own files.

- **Title music** starts as soon as you land on a preset and crossfades with the previous one; it plays once, like the title screen. Recent tracks are cached so flipping back is instant. Two streamed tracks (OGG/MP3/modules) can't overlap in SDL_mixer, so the next one waits for the previous fade-out. It's the MAPINFO `titlemusic` if set, otherwise the IWAD's own title lump (`D_DM2TTL`, `D_INTRO`, `MUS_TITL`, ...), searched in override order. OGG/MP3/FLAC and tracker modules stream through SDL_mixer; MUS is converted to MIDI and MIDI is rendered with a SoundFont.
- **SoundFont** for MIDI, first match wins: `--soundfont <file>`, the `DOOMRUNNER_SOUNDFONT` env var, any `.sf2`/`.sf3` in this project's `soundfonts/` folder, then any shipped next to a configured engine (its folder or a `soundfonts/` subfolder). The largest file in a tier is used. No SoundFont means MIDI tracks stay silent.
- **Readme** is a same-named `.txt` beside the map/mod file, or a readme/credits text at the root of a PK3. Map packs are checked before mods. idgames-style headers fill the author, year and description under the title.
- **Logos** replace the text title in the details panel: the preset's own main-menu logo (`M_DOOM`, `M_HTIC`, `M_STRIFE`), or the IWAD's when nothing else is loaded. Mods that re-ship or recolour the stock logo, and blank, full-screen or frame-shaped "logos", keep the text title.
- **ENDOOM** is the 80x25 text screen ports show on exit. The tab appears only when the preset's own files ship one (`ENDOOM`, `ENDTEXT`, `ENDSTRF`); the stock IWAD screen is skipped.
- **Colours follow the title art**: the most vivid hue in the art tints the background, labels, stripe and selection bar, and crossfades with the art. Red/orange, grey or dark art keeps the house red and gold.
- **UI sounds** are Doom's own menu sounds (`DSPSTOP`, `DSPISTOL`, `DSSWTCHN`, `DSSWTCHX`, `DSOOF`) read from the IWAD most of your presets use. No Doom-format IWAD, no sounds.
- The audio device is released while a game runs.

## Notes

- The backdrop is each preset's own title screen, read from its files in engine override order: a MAPINFO `titlepage`, then `TITLEPIC`, then Heretic/Hexen's raw `TITLE`. WAD and PK3/IPK3 are supported; PK7 is not.
- Button prompts are [Kenney's Input Prompts](https://kenney.nl/assets/input-prompts) (CC0, `assets/prompts/`). The style follows the pad you last pressed a button on: Xbox, PlayStation (detected by name) or Switch.
- Last played preset and the music toggle are stored in `state/last_played.json`.
- Crashes under `pythonw` (no console) are written to `state/couch-doom.log`.
- Map packs that point at a folder load every game file inside it, sorted by name.
- Supported option groups: launch mode (map/save), gameplay flags, compat flags, video resolution/FPS, audio mute. Multiplayer and demo options are ignored.

## License

MIT, see [LICENSE](LICENSE). Button prompts are CC0 (see above).
