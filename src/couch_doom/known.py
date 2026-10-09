"""Everything CouchDoom knows about specific WADs by name, kept in one place.

Credits and blurbs for games that ship or circulate without a readme of their own, the odd title picture no rule would
find, which IWADs are add-ons, and the IWAD file names recognised when a port has no iwadinfo of its own.

The official IWADs and add-ons are quoted from the publishers' own store text. The community entries further down
(`COMMUNITY`) are short factual lines written here, each citing the page they were checked against and the date, so a
stale one is easy to spot. Descriptions that can change (feature lists, version notes) are deliberately left out.
Matched by file name, so a renamed file just goes without.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Known:
    title: str
    author: str
    year: str
    description: str
    source: str
    art: str = ""  # path inside the archive of a title picture to use instead of the one the rules would find


_STEAM = "Steam store page"
_DOOM = Known(
    "DOOM", "id Software", "1993",
    "The demons came and the marines died...except one. You are the last defense against Hell. Prepare for the most "
    "intense battle you've ever faced. Experience the complete, original version of the game released in 1993, now "
    "with all official content and Episode IV: Thy Flesh Consumed.",
    _STEAM,
)
_SIGIL = Known(
    "SIGIL", "John Romero", "2019",
    "Created by id Software co-founder, John Romero, and released as an episode-sized mod consisting of 18 new maps, "
    "Sigil fits in between the timelines of DOOM (1993) and DOOM II. Baphomet, the gatekeeper of Hell, \"glitched the "
    "final teleporter with his hidden sigil, whose eldritch power brings you to even darker shores of Hell. You fight "
    "through this stygian pocket of evil to confront the ultimate harbingers of Satan, then finally return to become "
    "Earth's savior.\"",
    _STEAM,
)
_SIGIL2 = Known(
    "SIGIL II", "John Romero", "2023",
    "Embark on a nostalgic nightmare: Immerse yourself in the dark, demonic world of DOOM like never before. John "
    "Romero, the original Icon of Sin, takes you on a terrifying journey to commemorate the 30th anniversary of this "
    "legendary, first-person shooter. SIGIL II is DOOM's unofficial sixth episode. Upon breaching the pentagram of "
    "invulnerability in the final moments of SIGIL, Episode Five, you find yourself not on a victorious journey back "
    "to save Earth, but caught in Baphomet's cunning snare, catapulted into a new, grotesque domain of relentless "
    "torment, unending demon hordes, and an onslaught of heavy metal mayhem!",
    "SIGIL II's own text file",
)
_FREEDOOM = (
    "In 1999 id Software released the source code to their classic game Doom (under the GNU General Public License). "
    "The game as a whole did not get this treatment, however, which means that while the program code that powers "
    "Doom is free, the actual content of Doom - graphics, audio, levels, setting and characters - remains "
    "proprietary. The Freedoom project aims to fill this gap and create a complete free and libre first person "
    "shooter game."
)

KNOWN: dict[str, Known] = {
    "doom.wad": _DOOM,
    "doomu.wad": _DOOM,
    "doom2.wad": Known(
        "DOOM II: Hell on Earth", "id Software", "1994",
        "Hell has invaded Earth, and to save it, you must battle mightier demons with even more powerful weapons. "
        "This beloved sequel to the groundbreaking DOOM (1993) introduced players to the brutal Super Shotgun, the "
        "infamous Icon of Sin boss, and more intense FPS action.",
        _STEAM,
    ),
    "tnt.wad": Known(
        "Final DOOM: TNT: Evilution", "TeamTNT", "1996",
        "The UAC relocated their experiments to one of the moons of Jupiter. A spaceship, mistaken for a supply "
        "vessel, was granted access. But when it got close to the base, demons poured out. All your comrades were "
        "slaughtered or zombified. This time it's not about survival. It's about revenge.",
        _STEAM,
    ),
    "plutonia.wad": Known(
        "Final DOOM: The Plutonia Experiment", "Dario and Milo Casali", "1996",
        "Every effort has been made by the nation's top scientists to close the seven interdimensional Gates of Hell, "
        "but one portal remains open. Alone, you must infiltrate the ravaged base, defeat the demon Gatekeeper, and "
        "seal the last Hell portal before the undead take over the world.",
        _STEAM,
    ),
    "nerve.wad": Known(
        "No Rest for the Living", "Nerve Software", "2010",
        "To save Earth, you must descend into the stygian depths of hell. Battle nastier, deadlier demons and "
        "monsters with your trusty Super Shotgun. Survive more mind-blowing explosions and take part in the bloodiest, "
        "fiercest, most awesome blastfest ever. Recruit your friends and plow through 9 all-new levels in the new "
        "episode, No Rest for the Living!",
        "Xbox Live Arcade listing",
    ),
    "masterlevels.wad": Known(
        "Master Levels for DOOM II", "Independent designers", "1995",
        "This expansion includes twenty additional levels, all with the same hell-spawned horrors and action of the "
        "base game. Each level was created by independent designers and supervised by id Software.",
        _STEAM,
    ),
    "id1.wad": Known(
        "Legacy of Rust", "id Software, Nightdive Studios and MachineGames", "2024",
        "Created in collaboration by id Software, Nightdive Studios, and MachineGames, Legacy of Rust is the newest "
        "episode for DOOM, and the first official episode since DOOM II to feature new demons and weapons. This "
        "16-map Episode is broken up into two 8 map sections: The Vulcan Abyss and Counterfeit Eden.",
        _STEAM,
    ),
    "sigil.wad": _SIGIL,
    "sigil_v1_21.wad": _SIGIL,
    "sigil_v1_2.wad": _SIGIL,
    "sigil_v1_0.wad": _SIGIL,
    "sigil2.wad": _SIGIL2,
    "sigil_ii_v1_0.wad": _SIGIL2,
    "sigil_ii_mp3_v1_0.wad": _SIGIL2,
    "heretic.wad": Known(
        "Heretic", "Raven Software", "1994",
        "In a realm corrupted by the evil magic of three brothers known as the Serpent Riders, you are a heretic. As "
        "one of the last Sidhe elves, and a capable mage, you embark on a quest for vengeance against those who "
        "slaughtered your friends, family, and entire race.",
        _STEAM,
    ),
    "hexen.wad": Known(
        "Hexen: Beyond Heretic", "Raven Software", "1995",
        "While the Sidhe elf Corvus battled the evil forces of D'Sparil, the remaining Serpent Riders were busy "
        "corrupting other dimensions. As a Warrior, Mage, or Cleric, you must defend your realm of Cronos from the "
        "second Serpent Rider known as Korax.",
        _STEAM,
    ),
    "hexdd.wad": Known(
        "Hexen: Deathkings of the Dark Citadel", "Raven Software", "1996",
        "Hexen: Deathkings of the Dark Citadel is a dark fantasy first-person shooter and expansion to Hexen: Beyond "
        "Heretic. After discovering the Chaos Sphere, you have been transported to the Realm of the Dead. Now, your "
        "only way home is blocked by the Dark Citadel.",
        _STEAM,
    ),
    "strife1.wad": Known(
        "Strife: Quest for the Sigil", "Rogue Entertainment", "1996",
        "Immerse yourself in this all-consuming epic quest that for the first time combines riveting role-playing "
        "adventure with the spectacular Doom 3D engine! An evil presence has implanted itself in the fabric of our "
        "world. Play the role of spy, assassin, warrior and thief as you are lured into the darkest and most perilous "
        "adventure of your life. You'll have Blackbird on your side - a seductive underground agent that will provide "
        "you with clues as you encounter progressively more sinister foes. Be strong, and trust no one.",
        _STEAM,
    ),
    "freedoom1.wad": Known("Freedoom: Phase 1", "The Freedoom project", "", _FREEDOOM, "freedoom.github.io"),
    "freedoom2.wad": Known("Freedoom: Phase 2", "The Freedoom project", "", _FREEDOOM, "freedoom.github.io"),
    "hacx.wad": Known(
        "Hacx", "Banjo Software", "1997",
        "HACX is an action filled DOOM Engine game. The story is set in the near future, where you'll find yourself "
        "engrossed in an international blastfest. Wield weapons of mass destruction from China to Paris to combat a "
        "devilish artificial intelligence and its hordes of loyal fanatics. Can you handle it, hacker?",
        "HACX.TXT",
    ),
    "square1.pk3": Known(
        "The Adventures of Square", "BigBrik Games", "2014",
        "The brilliant Doctor Octagon has been kidnapped! Square must find him, and rescue him from the clutches of "
        "the Circle of Evil, a mysterious cult hellbent on the domination of Shape Land. He will square off against "
        "terrible monsters and impossible traps in order to prove that he's no square when it comes to justice. Guide "
        "him to the center of the Circles' domain, unravel their malicious plot, and win the day fair and square!",
        "adventuresofsquare.com",
    ),
    "chex3.wad": Known(
        "Chex Quest 3", "Charles Jacobi", "2008",
        "In 1996 Ralston Foods was looking for a simple game that could fit on a CD-ROM which they could distribute "
        "in their boxes of Chex cereal. A quick demo level proved that the \"zorch them back to their own dimension\" "
        "concept would work yet still retain the fun gameplay of Doom. Chex Quest 3 is a full-blown sequel, and "
        "includes the original Chex Quest 1 and 2 levels.",
        "CQ3 ReadMe.txt",
    ),
    "blasphem.wad": Known(
        "Blasphemer", "The Blasphemer project", "",
        "Blasphemer aims to create a free content package for the Heretic engine, with a theme of metal-inspired dark "
        "fantasy.",
        "github.com/Blasphemer/blasphemer",
    ),
}


_CHECKED = "checked 2026-10-08"
_ASHES = (
    "A post-apocalyptic total conversion for GZDoom that mixes old-school Build-style level design and Doom action "
    "with a touch of Stalker and Fallout."
)

_MYHOUSE = Known(
    "MyHouse", "Veddge", "2023",
    "A single-map GZDoom project for Doom II, presented as a tribute to the author's late friend: a suburban house "
    "that keeps changing shape, with non-linear exploration, puzzles and several endings. Best played knowing as "
    "little as possible. A 2023 Cacoward winner.",
    f"doomwiki.org/wiki/My_House, doomworld.com/cacowards/2023/myhouse ({_CHECKED})",
)

# Community projects, matched by file name or, for versioned downloads, by the start of the name (see lookup()).
COMMUNITY: dict[str, Known] = {
    "myhouse.wad": _MYHOUSE,
    "myhouse.pk3": _MYHOUSE,
    "moonbld.wad": Known(
        "Moonblood", "Deadwing", "2017",
        "A 32-map Doom II megawad in six episodes, with small to medium maps, vanilla-style mechanics and a custom "
        "soundtrack. It began as a remake of the author's first WAD, Eclipse, and draws on Scythe, Jenesis, Mano Laikas "
        "and the Doom the Way id Did series.",
        f"doomwiki.org/wiki/Moonblood, wad-archive.com ({_CHECKED})",
    ),
    "the thing you cant defeat": Known(
        "The Thing You Can't Defeat", "YourOpinionsAreWRONG", "2022",
        "An experimental eight-map WAD for Ultimate Doom, built for GZDoom. You replay the first episode as it slowly "
        "morphs into a confusing nightmare, since Doomguy has dementia. Inspired by \"Doom but something's not right\" and "
        "The Caretaker's album Everywhere at the End of Time, with music by William Dinsdale.",
        f"doomworld.com/forum/topic/130478 ({_CHECKED})",
    ),
    "av.wad": Known(
        "Alien Vendetta", "Anders Johnsen and others", "2001",
        "A 32-level Doom II megawad for the vanilla engine. It started as a Hell Revealed follow-up and settled between "
        "that and a classic megawad: detailed architecture and varied themes, with hard gameplay that sits above "
        "The Plutonia Experiment. One of the most influential PWADs, and one of the few allowed in Compet-N speedruns.",
        f"doomwiki.org/wiki/Alien_Vendetta ({_CHECKED})",
    ),
    "hr.wad": Known(
        "Hell Revealed", "Yonatan Donner, Haggay Niv", "1997",
        "A 32-level Doom II megawad for the vanilla engine, famous for its extreme difficulty. It has full skill-level "
        "support so less experienced players can still finish it, plus new graphics and cooperative extras. It is one "
        "of the few PWADs allowed in Compet-N speedruns.",
        f"doomwiki.org/wiki/Hell_Revealed ({_CHECKED})",
    ),
    "mm2.wad": Known(
        "Memento Mori II", "MM2 Crew", "1996",
        "A 32-level Doom II megawad for the vanilla engine and the sequel to Memento Mori, made by a large team that "
        "includes the Innocent Crew. Designed especially for cooperative play, with new graphics, music and a story. "
        "One of the few PWADs allowed in Compet-N speedruns.",
        f"doomwiki.org/wiki/Memento_Mori_II ({_CHECKED})",
    ),
    "abysm x - dance of blood": Known(
        "Abysm X: Dance of Blood", "Jazzmaster9", "2026",
        "A spin-off sequel to Abysm 2 and a Doom II total conversion for GZDoom: a dark action RPG in the spirit of "
        "Diablo, Dark Souls and Strife. Three worlds hang off a central hub, you pick a Warrior, Berserker or Sorcerer, "
        "and fast Doom combat is mixed with attributes, crafting and inventory. Version 1.0 came out in July 2026.",
        f"modstalgia.com/doom-ii-hell-on-earth/mods/abysm-x-dance-of-blood ({_CHECKED})",
    ),
    "voxel_parallax_doomii.pk3": Known(
        "Voxel Doom II with Parallax Textures", "Cheello and others", "2023",
        "A visual addon for GZDoom that replaces the monsters, weapons, props and items with 3D voxel models and adds "
        "depth to wall and floor textures with parallax. Needs GZDoom 4.10 or newer.",
        f"moddb.com/mods/voxel-doom-ii ({_CHECKED})",
    ),
    "castlevania.ipk3": Known(
        "Castlevania: Simon's Destiny", "Batandy", "2017",
        "A standalone first-person fan game for GZDoom that reimagines the first NES Castlevania, with its six levels "
        "rebuilt as Doom maps. Jumping and platforming matter, and the soundtrack draws on fan remixes and official "
        "Castlevania albums.",
        f"doomwiki.org/wiki/Castlevania:_Simon%27s_Destiny, batandy.itch.io/simonsdestiny ({_CHECKED})",
    ),
    "harmony.wad": Known(
        "Harmony", "Thomas van der Velden", "2009",
        "A total conversion based on Doom II and built for ZDoom, set in a post-apocalyptic world where most men have "
        "mutated into monsters. Its art is distinctive: the enemies were made from photographs of clay sculptures. "
        "A 2009 Cacoward winner.",
        f"doomwiki.org/wiki/Harmony ({_CHECKED})",
    ),
    "technicolor.pk3": Known(
        "Technicolor Antichrist Box", "Major Arlene", "2020",
        "A single-map GZDoom project for Doom II, set in a floating citadel in a void of vivid cyan and magenta. It "
        "uses the Supercharge gameplay mod and was a 2020 Cacoward runner-up.",
        f"doomwiki.org/wiki/Technicolor_Antichrist_Box ({_CHECKED})",
    ),
    "idkfav2.wad": Known(
        "IDKFA", "Andrew Hulshult", "2016",
        "A remake of the original Doom soundtrack, rearranged and played on real instruments, packaged as a music "
        "pack for source ports that can play OGG. The tracks were composed by Bobby Prince.",
        f"doomwiki.org/wiki/IDKFA_-_Knee-Deep_in_the_Dead ({_CHECKED})",
    ),
    "rr.pk3": Known(
        "Refracted Reality", "killerkouhai and others", "2021",
        "A GZDoom megawad for Doom II with 15 surreal maps in colorful, void-like settings. It keeps the vanilla "
        "weapons and monsters, apart from a new final boss.",
        f"doomwiki.org/wiki/Refracted_Reality ({_CHECKED})",
    ),
    "bloom.pk3": Known(
        "Bloom", "Bloom Team", "2021",
        "A Doom and Blood crossover for GZDoom: hybrid monsters, Blood's environments and weapons, and a new "
        "episode. You can play as Doomguy or Caleb.",
        f"en.wikipedia.org/wiki/Bloom_(mod), moddb.com/mods/bloom-doomblood-crossover ({_CHECKED})",
    ),
    "elementalism_phase1": Known(
        "Elementalism: Phase 1", "Various", "2022",
        "A GZDoom megawad for Doom II with 15 maps in three episodes themed on Earth, Water and Fire, with custom "
        "monsters and bosses and an original soundtrack. A 2022 Cacoward winner.",
        f"doomwiki.org/wiki/Elementalism ({_CHECKED})",
    ),
    "doom_infinite_demo": Known(
        "Doom Infinite", "DifficultOldStuff", "2023",
        "A roguelike gameplay mod for GZDoom. You play randomly chosen Doom levels that mutate as a curse builds, "
        "with a stats system, weapon mods and powerups. A 2023 Cacoward winner.",
        f"doomwiki.org/wiki/Doom_Infinite ({_CHECKED})",
    ),
    "doomrl_arsenal": Known(
        "DoomRL Arsenal", "Yholl, Ryan Cordell and others", "2013",
        "A gameplay mod for ZDoom and GZDoom inspired by the roguelike DoomRL, bringing its weapons, mod packs, armor "
        "and character classes into Doom and Doom II. A 2015 Cacoward winner.",
        f"doomwiki.org/wiki/DoomRL_Arsenal ({_CHECKED})",
    ),
    "doomrl_monsters": Known(
        "DoomRL Monster Pack", "Yholl, Ryan Cordell and others", "2013",
        "The official add-on for DoomRL Arsenal: many new and altered enemies, plus extra difficulty levels such as "
        "Nightmare, Technophobia and Armageddon.",
        f"doomwiki.org/wiki/DoomRL_Arsenal ({_CHECKED})",
    ),
    "abysm - dawn of innocence": Known(
        "Abysm: Dawn of Innocence", "Jazzmaster9", "2018",
        "A GZDoom total conversion for Doom II: a dark-fantasy action RPG with a hub world, quests, medieval weapons "
        "and spells, leveling, and an original soundtrack by John Weekley (PRIMEVAL). It has 17 maps.",
        f"doomwiki.org/wiki/Abysm:_Dawn_of_Innocence ({_CHECKED})",
    ),
    "abysm 2 - infernal contract": Known(
        "Abysm 2: Infernal Contract", "Jazzmaster9", "2020",
        "The sequel to Abysm: Dawn of Innocence, a GZDoom action RPG total conversion. A 2020 Cacoward runner-up.",
        f"doomwiki.org/wiki/Abysm:_Dawn_of_Innocence, doomworld.com/cacowards/2020 ({_CHECKED})",
    ),
    "zmc-bwv": Known(
        "Brutal Wolfenstein 3D", "Zio McCall", "2014",
        "A Doom II mod that rebuilds Wolfenstein 3D in the spirit of Brutal Doom: excessive gore, new weapons, enemies "
        "and graphics, and redesigned maps.",
        f"wl6.wolfenstein3d.nl/Brutal_Wolfenstein_3D, moddb.com/mods/brutal-wolfenstein-3d ({_CHECKED})",
        art="graphics/wlfend.png",  # the title is a 3D map; its end screen is the castle gate under the logo
    ),
    "ashes2063enriched": Known(
        "Ashes: 2063 (Enriched)", "", "2021",
        f"{_ASHES} This is the first episode.",
        f"moddb.com/mods/ashes-2063 ({_CHECKED})",
    ),
    "ashesafterglow": Known(
        "Ashes: Afterglow", "", "2021",
        f"{_ASHES} This is the second episode.",
        f"moddb.com/mods/ashes-2063 ({_CHECKED})",
    ),
    "asheshardreset": Known(
        "Ashes: Hard Reset", "", "2021",
        f"{_ASHES} This is a prequel to Afterglow.",
        f"moddb.com/mods/ashes-2063 ({_CHECKED})",
    ),
}


# Add-on IWADs the engine loads on top of their base game (iwadinfo's "Required"); alone they have no title
# screen, music or logo.
ADDON_IWADS = {"hexdd.wad": "hexen.wad", "sve.wad": "strife1.wad"}

# The port's own iwadinfo decides names and order; without it, these file names are still recognised.
IWAD_NAMES = (
    "doom_complete.pk3", "doom2.wad", "doom2xbox.wad", "doom2unity.wad", "doom2kex.wad", "doom2f.wad", "doomu.wad",
    "doom.wad", "doomxbox.wad", "doomunity.wad", "doomkex.wad", "doom1.wad", "bfgdoom.wad", "bfgdoom2.wad",
    "doombfg.wad", "doom2bfg.wad", "plutonia.wad", "plutoniaunity.wad", "plutoniakex.wad", "tnt.wad",
    "tntunity.wad", "tntkex.wad", "freedoom1.wad", "freedoom2.wad", "freedoomu.wad", "freedoom.wad", "freedm.wad",
    "heretic.wad", "hereticsr.wad", "heretic1.wad", "hexen.wad", "hexdd.wad", "hexendemo.wad", "hexdemo.wad",
    "strife1.wad", "sve.wad", "strife0.wad", "strife.wad", "blasphem.wad", "blasphemer.wad", "chex.wad",
    "chex3.wad", "action2.wad", "harm1.wad", "hacx.wad", "hacx2.wad", "square1.pk3", "delaweare.wad", "rotwb.wad",
)


def lookup(file_name: str) -> Known | None:
    """The entry for a file: an exact name, or a community entry whose key starts the name (versioned downloads)."""
    name = file_name.lower()
    if found := KNOWN.get(name):
        return found
    if found := COMMUNITY.get(name):
        return found
    return next((k for key, k in COMMUNITY.items() if not key.endswith((".pk3", ".wad", ".ipk3")) and name.startswith(key)), None)
