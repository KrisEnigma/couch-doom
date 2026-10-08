# Changelog

Each release's notes on GitHub are its own section below, behind the download instructions in `packaging/release-header.md`. Keep the `**New in X.Y.Z**` heading format: the release workflow and the in-app update notice both look for it.

**New in 0.7.3**
- Title music now plays for mods that start it from a script instead of declaring it, such as Castlevania: Simon's Destiny: a pk3 track named like a title song is used when nothing else is found.

**New in 0.7.2**
- Linux: games no longer fail to start with errors like "GLIBCXX not found". CouchDoom's own libraries were leaking into the games it launched; they now start with a clean environment.

**New in 0.7.1**
- A troubleshooting log: every game launch is recorded in `couch-doom.log` with its command line, exit code and the engine's last output, so a port that won't start can be diagnosed. It is capped at about 512 KB.
- If a game closes right away, CouchDoom now says so and shows the engine's own last message, instead of just returning to the list.
- Linux: an AppImage engine that fails to start because the system lacks FUSE is now retried automatically by unpacking itself.

**New in 0.7.0**
- Intel Macs and Linux on ARM now have their own downloads, and the Linux builds run on older distributions (glibc 2.28 or newer, such as Ubuntu 20.04).
- Fixed: on macOS older than the build machine, the title music silently didn't play. The Mac builds now support macOS 10.15 (Intel) and 11 (Apple Silicon) or newer.

**New in 0.6.0**
- The official games now have credits and a description in the info sheet: Doom, Doom II, Final Doom, No Rest for the Living, Master Levels, Legacy of Rust, SIGIL, Heretic, Hexen, Strife, Freedoom, Hacx, Chex Quest 3, Blasphemer and The Adventures of Square. The texts come from their store pages, readmes and official sites.
- The info sheet always opens on the readme, and the command-line tab is gone. The file path is no longer shown.
- Title music now plays for games that rename their tracks through Dehacked (Hacx) or set it in an included MAPINFO file (The Adventures of Square).
- Music starts faster: title tracks are capped at 30 seconds and fade out at the cut, so long MIDI songs no longer take seconds to start.
- A notice when a newer release is out, shown once per launch: open the release page, remind me next time, or don't remind me about that version. It can be turned off (see the README).
- A new app icon, and the taskbar now shows it instead of Python's.

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
