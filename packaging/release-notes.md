**Download the file for your system below, unpack it anywhere, and start CouchDoom.** No Python or installer needed.

- **Windows:** `CouchDoom-…-windows-x64.zip`, then run `CouchDoom.exe`. On the "unknown publisher" warning, click **More info → Run anyway** (the app isn't code-signed).
- **macOS (Apple Silicon):** `CouchDoom-…-macos-arm64.zip`, then open `CouchDoom.app`. If macOS says it can't be opened, go to **System Settings → Privacy & Security** and click **Open Anyway**.
- **Linux (x86-64):** `CouchDoom-…-linux-x64.tar.gz`, then run `./CouchDoom`. Needs glibc 2.35 or newer (Ubuntu 22.04, Fedora 36 or later). On Arch you can also build `packaging/aur/PKGBUILD` with `makepkg -si`.

You need [DoomRunner](https://github.com/Youda008/DoomRunner), [ZDL](https://github.com/lcferrum/qzdl) or [Doom Launcher](https://github.com/nstlaurent/DoomLauncher) with at least one game set up, or just GZDoom, UZDoom or VKDoom with an IWAD. CouchDoom finds its settings automatically; if you have more than one launcher, it asks which to use (switch later with L3 / F4).

**New in 0.6.0**
- The official games now have credits and a description in the info sheet: Doom, Doom II, Final Doom, No Rest for the Living, Master Levels, Legacy of Rust, SIGIL, Heretic, Hexen, Strife, Freedoom, Hacx, Chex Quest 3, Blasphemer and The Adventures of Square. The texts come from their store pages, readmes and official sites.
- The info sheet always opens on the readme, and the command-line tab is gone. The file path is no longer shown.
- Title music now plays for games that rename their tracks through Dehacked (Hacx) or set it in an included MAPINFO file (The Adventures of Square).
- Music starts faster: title tracks are capped at 30 seconds and fade out at the cut, so long MIDI songs no longer take seconds to start.

**New in 0.5.0**
- macOS and Linux downloads, alongside Windows.
- No launcher needed: point it at GZDoom, UZDoom or VKDoom (or let it find them) and it lists your IWADs exactly like the port's own startup picker, including Steam, GOG and Bethesda.net copies.
- macOS support: Retina rendering, the window comes to the front, fullscreen stays on the current Space, and **Find it myself…** uses the native file dialog.
- Doom Launcher: only actual games are listed. Patches, music WADs and engine files that Doom Launcher keeps in its library no longer show up as extra entries.
- Crisper text on every OS: real Barlow Bold and JetBrains Mono fonts are bundled instead of synthetic bold.
- The line under the title now reads "From DoomRunner" (or whichever launcher you use).

**New in 0.4.0**
- Linux support: finds DoomRunner (including Flatpak) and qZDL settings in their standard Linux folders, recognises their programs and AppImages when dropped on the window, and uses zenity or kdialog for **Find it myself…**. Tested on Arch Linux with DSDA-Doom.
- Installed copies (pip, AUR) keep their state in your user folder instead of beside the code.
- The version is shown next to the CouchDoom title.

**New in 0.3.1**
- DSDA-Doom, PrBoom+, Woof, Nugget, Chocolate/Crispy Doom, EDGE and other non-ZDoom ports now get the same per-engine flags DoomRunner gives them (`-save`, `-complevel`, `-merge` and so on), instead of ZDoom-only ones that could stop them from starting.
- DoomRunner's custom-argument entries in the mod list are passed along, and ZDoom compatibility options now match DoomRunner's command line.

**New in 0.3.0**
- Works with ZDL, Doom Launcher and Doom Launcher 667, not just DoomRunner.
- First-run picker when more than one launcher is found; switch any time with L3 / F4.
- Finds portable launchers through your Start Menu, Desktop and taskbar shortcuts. If it still can't, pick **Find it myself…** or drag the launcher's exe onto the window.

See `How to use.txt` in the download for controls and optional MIDI music setup.
