**Download `CouchDoom-…-windows-x64.zip` below, unzip it anywhere, and double-click `CouchDoom.exe`.** No Python or installer needed.

You need [DoomRunner](https://github.com/Youda008/DoomRunner), [ZDL](https://github.com/lcferrum/qzdl) or [Doom Launcher](https://github.com/nstlaurent/DoomLauncher) with at least one game set up, or just GZDoom, UZDoom or VKDoom with an IWAD. CouchDoom finds its settings automatically; if you have more than one launcher, it asks which to use (switch later with L3 / F4). Windows may show an "unknown publisher" warning because the app isn't code-signed: click **More info → Run anyway**.

On Arch Linux, an AUR package is coming soon; until then, build it from the repo's `packaging/aur/PKGBUILD` with `makepkg -si` (see the README). Other Linux distros can run it from source.

**New in 0.5.0**
- No launcher needed: point it at GZDoom, UZDoom or VKDoom (or let it find them) and it lists your IWADs exactly like the port's own startup picker, including Steam, GOG and Bethesda.net copies.
- macOS support from source: Retina rendering, the window comes to the front, fullscreen stays on the current Space, and **Find it myself…** uses the native file dialog.
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

See `How to use.txt` in the zip for controls and optional MIDI music setup.
