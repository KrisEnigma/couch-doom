# Stream-Cached Music: Design Spec

## Goal

Keep title music responsive on low-memory, slow-storage machines while avoiding repeated extraction and decompression of non-MIDI tracks from WAD/PK3 files.

## Current behavior

- `music.find_title_music()` asks `Archives` for `bytes`; every candidate track is fully read before its type is known.
- `archive.Zip.lump()` calls `Zip.read()`, which fully decompresses a PK3 member to memory. `Wad.lump()` reads the full lump. Embedded WAD lumps may also enter `_EMBED_LUMPS` (up to 48 MiB total).
- `music._prepare()` stores both rendered MIDI PCM and encoded OGG/MP3/etc. bytes in `MusicPlayer.cache` (96 MiB target, but one oversize item is retained).
- `MusicPlayer._start()` passes encoded bytes to Pygame through `io.BytesIO`; playback decodes as a stream, but the encoded track remains memory-backed.
- `asset_cache` is a separate JSON disk cache for title art, logos, readmes and ENDOOM. It does not cache music.

## Desired behavior

1. Preserve title-track precedence and recognition: MAPINFO title music, TITLEMAP music, ACS script references, game-default music lumps, then title-named PK3 entries. Preserve DeHackEd/BEX renames and MUS-to-MIDI conversion.
2. Read MIDI/MUS bytes only when selected. Convert MUS, render with the selected engine's configured/included SoundFont, and keep only rendered PCM in a small bounded in-memory cache.
3. For OGG, MP3, FLAC, WAV and tracker formats, identify the archive member/lump from a short prefix, then copy it in chunks to a persistent music cache. Do not hold the encoded stream in `MusicPlayer.cache`.
4. Play cached non-MIDI files by path through Pygame's streaming music API. The source archive is never read during playback.
5. Persist a small, versioned track-selection manifest keyed by preset and source-file identity. On unchanged inputs, it lets CouchDoom reopen the source descriptor without re-scanning PK3 entries or reparsing embedded-WAD directories. Store negative results too.
6. Keep archive reads, MUS conversion, MIDI rendering and stream extraction on the existing music worker. Cancellation must stop chunk copies and remove partial cache files.
7. Keep the disk cache bounded and safe to clear. A cache failure must be logged and must not crash CouchDoom; use an in-memory fallback only for streams no larger than 8 MiB, otherwise skip that preview with a clear log entry.
8. Preserve the current sourceport-first SoundFont selection, per-preset renderer identity and explicit `--soundfont` / `DOOMRUNNER_SOUNDFONT` overrides.

## Cache policy

### Lookup and population order

The existing title-asset lifecycle in `ui._load_extras` is: unpack/resolve inputs → `asset_cache.key_for` → `asset_cache.get` → on miss scan and extract art/logo/readme/ENDOOM (including startup-art fallback) → `asset_cache.put` → return raw assets. UI conversion then creates Pygame surfaces and keeps title art in its process-memory LRU. Separately, `ui._warm_cache` visits presets breadth-first from the current selection, then prunes and invalidates persistent entries.

Use the same lookup/populate/prune ordering for music, adapted to its streamed payload:

1. Build a selection key from preset identity and ordered archive paths/stat data, with a finder-version component. Read the selection manifest first. A hit returns the selected source descriptor or a cached no-track result without archive discovery.
2. On a selection miss, run the current ordered music finder and atomically save its result. This avoids rescanning unchanged PK3s and embedded-WAD directories on later launches.
3. For MIDI/MUS, read and render the selected source, then put only PCM in the bounded process-memory LRU.
4. For other formats, check the content-addressed payload cache; on a miss, stream into a unique `.part`, validate and atomically publish. Touch access time on hit.
5. After payload population, prune by payload-file access time toward the 256 MiB target while protecting newly prepared, pending, and active mixer paths. The target may be exceeded while protected files are in use; prune again when released. Manifest invalidation by active preset keys and payload size pruning are separate operations. The `assets/` cache keeps its existing independent 512 MiB limit and behavior.

The shared cache-root helper centralizes platform path selection only. Do not unify asset and music serialization, keys, limits, or invalidation: asset JSON is keyed by a preset's entire input set; stream payloads are keyed by one source member/lump and can be shared across presets. Unlike image warm-up, music stays on-demand for the selected preset and does not prewarm neighboring tracks, avoiding unnecessary archive I/O and disk writes.

- Root: the existing per-user CouchDoom cache root, with a `music/` child (`~/Library/Caches/CouchDoom/music` on macOS).
- Key: SHA-256 over the resolved source archive path, archive mtime and size, source locator (ZIP member or WAD lump/range), uncompressed length, and ZIP CRC when available. This follows the existing asset-cache invalidation policy and lets the same source be shared by presets.
- Selection manifest: SHA-256 over the same preset fields and ordered input path/stat conventions as `asset_cache.key_for`, plus a finder-version integer. Store selected track kind/format/name and a serializable source descriptor, or an explicit no-track result. A stale/corrupt/version-mismatched manifest is ignored and rebuilt.
- Writes: chunk to a sibling `.part` file, check cancellation between chunks, verify expected byte count, then atomically replace the final path. Remove partial files on errors/cancellation.
- Disk target: 256 MiB, evict least-recently-used cache files by access time; never prune newly prepared, pending, or active stream files. The target may be exceeded while protected files are in use, then pruning catches up after release. Delete stale `.part` files on startup.
- Memory cap: 24 MiB for rendered MIDI PCM, strictly enforced even when one track exceeds the cap. The currently playing sound is held by the mixer until playback ends, but it does not remain in the reusable PCM cache after eviction.

## Archive-source design

Add a reopenable `ArchiveSource` descriptor. It must outlive the `Archives` context without retaining open archive handles and provide:

- `read_prefix(limit) -> bytes`, capped at 1084 bytes (enough for the current module signatures).
- `copy_to(destination, cancel, chunk_size=256 KiB) -> int`, streaming a WAD range, a ZIP/PK3 member, or a WAD lump inside a ZIP/PK3 member.
- a stable identity containing the archive path/stat data and member/lump locator.

For embedded WADs, retain the outer PK3 path and embedded WAD member name. Reopening that member as a `ZipExtFile` and seeking to the WAD lump may require inflating bytes up to the lump offset; this work stays in the background and does not allocate the whole track. The final track itself is copied to the persistent cache so later launches do not repeat that inflate.

The first lookup after a preset/archive change may still inflate an embedded WAD while finding its directory and track. The selection manifest avoids repeating that scan on later launches as long as the preset's source files are unchanged.

## Out of scope

- Changing which title track is selected or adding support for new formats.
- Caching all WAD/PK3 contents, soundfonts, or decoded PCM for non-MIDI files.
- Running a release workflow or publishing a build as part of this refactor.
