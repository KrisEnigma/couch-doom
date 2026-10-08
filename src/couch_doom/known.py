"""Credits and blurbs for the official IWADs and add-ons, which ship without a readme.

Descriptions are quoted from the publishers' own store text, not written here; `source` says where from.
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
