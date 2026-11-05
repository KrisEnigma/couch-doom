# Changelog

Each release's notes on GitHub are its own section below, behind the download instructions in `packaging/release-header.md`. Keep the `**New in X.Y.Z**` heading format: the release workflow and the in-app update notice both look for it.

**New in 1.2.8**

- Title music is back. The 1.2.7 downloads were built without the MIDI player.

**New in 1.2.7**

- The window can be resized, and it opens at the size you left it.
- On Windows, moving a full-screen window to another monitor corrects its size and resolution to fit that monitor.
- A release you chose not to be reminded about can still be installed from Help. `--force-update` reinstalls the latest release.
- Refresh list counts the games it is caching, picks up edits to a text file beside a game or to descriptions.json, and says Refreshed when it finishes.
- Cache files are named after the preset.

**New in 1.2.6**

- The 60 frames-per-second cap is gone. CouchDoom now draws through your graphics card on Mac, Windows and Linux, and scrolling keeps up with the display, including high refresh rate screens.
- Alt+Enter switches between full screen and a window, and the menu has a Full screen option. CouchDoom remembers your choice for next time.
- Title music now starts with the artwork instead of trailing behind it. Moving to the next preset starts its music sooner.
- Presets made of several files show the right art: the title art, logo and description come from the first file that has them, so a mod loaded after a map no longer covers that map's logo.
- macOS: an Intel copy running on Apple Silicon is offered the native Apple Silicon download, and installing it no longer crashes.
- The update notice and What's new show each change in full, and list five of them.
- Selecting a game in Recently Played no longer also slides that game in its own group.

**New in 1.2.5**

- The Last hint jumps to the last game you played. With Recently Played on, pressing it again moves between that group and the game's own group.
- Windows and Linux: an update keeps files you added in the CouchDoom folder, such as a note or the installer. The program itself is still replaced.
- macOS: the Dock keeps CouchDoom's icon instead of switching to pygame's when the window opens and after a game. On Intel Macs, quitting after title music no longer crashes. An Intel copy on Apple Silicon is offered the Apple Silicon download even when the version number is the same, and installing an update no longer ends in a crash report.

**New in 1.2.4**

- Refresh list now picks up a readme you've edited beside a game. Title art stays cached.
- If a mod bundle can't be read, the log names the game and the bundle that listed the missing file, including a bundle inside another bundle.

**New in 1.2.3**

- Games added through a DoomRunner .dmb bundle now show their readme, and a readme you add later shows up without clearing anything.
- After an update, a What's new screen lists every change since the version you had, even if you skipped a few releases.
- Moving between games crossfades the title art faster and without a dark film that flashed over it mid-change.
- Updates on Windows install reliably, and CouchDoom closes straight away instead of showing a restart screen.
- Installing an update on a Mac no longer fails the certificate check.
- The first launch after updating rescans title art and music once, so it can take a little longer than usual.

**New in 1.2.2**

- Starting a game zooms its title art up to fill the screen, and the loading screen shows that art instead of a plain red one.
- Selecting a category shows its name in large type, with the games in it listed below, instead of one game's art.
- Larger, brighter text that's easier to read from the couch, and simpler titles on menus and dialogs.
- Search keeps the list in view while you type. Ctrl+Backspace deletes a whole word, and the file browser shows folder and drive icons.
- Title music fades as soon as you move to a game with different music.
- Future in-app updates show each step, can be cancelled while unpacking, and tell you whether they installed.

**New in 1.2.1**

- The launcher browser lists launcher programs and settings files first, labeled with their launcher, shows your drives' names, and tells you when a folder has nothing to open.
- Clearer help in every language: it covers the menu, uses the menu's real names, and tells you where to find the log when reporting a bug.
- Problems with a game's setup, such as a missing IWAD or mod, now appear in your language.
- Smoother browsing with less work per frame, and CouchDoom no longer draws while minimized.
- More reliable: changing a setting can't crash CouchDoom when another program briefly holds the settings file, and artwork for games in collapsed groups stays cached between launches.

**New in 1.2.0**

- Escape or Start opens a menu for refresh, title music, menu sounds, Language, choosing a launcher, Help, and Quit. Colors can follow each game's art or lock one look for the whole app.
- Menus, help, and prompts in English, Spanish, Brazilian Portuguese, French, and German; the first run starts in your system's display language.
- Optional Recently Played group (off by default). On a group heading, Tab or X expands or collapses every group at once.
- Home and End jump to the ends of the list and file browser; the browser uses Parent and Drives & Home instead of shoulder cycling. Selecting games feels snappier and big libraries use far less memory, and leftover folders from an interrupted update are cleaned up on the next launch.

**New in 1.1.0**

- A new in-app help guide explains how to find games, use favorites and controls, and get help or report a problem.
- Organize large game lists by collapsing groups. Favorites stay near the top, and search still finds games inside collapsed groups.
- The launcher browser can enter linked folders and hides hidden files unless you choose to show them.
- DoomRunner `.dmb` bundles and relative configuration paths are handled more reliably.
- SoundFont discovery and in-app update checks are more reliable, with clearer update-check logs.
- macOS downloads include a styled drag-to-Applications installer image.

**New in 1.0.0**

- Browse for launchers right inside CouchDoom, using your controller to navigate folders and choose files.
- Menu sounds are available even when no Doom IWAD is installed.
- Improved macOS window cleanup to prevent crashes.
- Fixed title music detection for standalone game archives.

**New in 0.8.0**

- Update CouchDoom from inside the app on Windows, macOS and Linux; it restarts when the update is done.
- More games and mods now play the right title music, and music starts faster.
- CouchDoom stays visible while games start and close, with edge-to-edge fullscreen on Mac.
- CouchDoom finds portable DoomRunner and UZDoom settings more reliably; controller prompts follow your last-used device.
- Steam Deck setup and library shortcut art are improved, and closing a game no longer shows unnecessary warnings.

**New in 0.7.4**

- Windows: fixed a crash when coming back from long play sessions with a gamepad, and the taskbar keeps CouchDoom's icon after a game.
- MIDI title music plays at an even volume, presets that share a track keep it playing, and Strife plays its real title song.
- Far more mods show their own title screen, logo and music, including Abysm, Elementalism, Doom Infinite, Bloom, Square, Brutal Wolfenstein and Simon's Destiny.
- Mods without title art use their loading screen as the background. Deathkings and Strife: Veteran Edition show their base game's title screen.

**New in 0.7.3**
- Title music now plays for mods that start it from a script instead of declaring it, such as Castlevania: Simon's Destiny: a pk3 track named like a title song is used when nothing else is found.
- Readmes are found more often: a readme beside the file with a slightly different name (spacing or a version number) now matches, a lone "readme" next to a single game file is used, and inside a pk3 the readme is chosen over the credits file.
- Descriptions for mods downloaded through the in-game mod browser: its `metadata` file (title, author, date and the full English description) is now read, and a text file a WAD carries inside itself (such as BTSX's) is used when there is no other readme.
- Readmes in the newer idgames layout for single maps (Map creator, Map description, Commentary) now show their author, title and description.
- Built-in descriptions for popular community projects (Harmony, Abysm, Ashes, Bloom, Elementalism, DoomRL Arsenal and more). They fill in when a mod's own readme has no description, and the readme's text stays below.
- Your own descriptions: put a `descriptions.json` in the state folder to give any mod a title, author, year and description. It takes priority over every other source (see the README).

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
