# Stream-Cached Music Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the executing-plans workflow and complete tasks inline, in order.

**Goal:** Read MIDI/MUS tracks on demand and stream every other title-music format from a bounded, persistent extracted-file cache.

**Architecture:** Follow the existing asset-cache lifecycle: derive a preset/input key, read a persistent result, compute on a miss, store the result, then prune old entries. Music has two persistent results in that lifecycle: a small selection manifest and extracted non-MIDI payloads. `archive.py` exposes reopenable sources; MIDI bytes are rendered into a separate bounded RAM LRU. Both operations stay on the existing music worker.

**Tech Stack:** Python 3.11+, `zipfile`, `pathlib`, WAD range reads, pygame-ce `mixer.music`, TinySoundFont, existing cross-platform smoke harness.

**Spec:** [Stream-Cached Music design](../specs/2026-10-29-stream-cached-music.md)

## Global Constraints

- Keep title-track precedence, MUS conversion, sourceport-specific SoundFonts, and explicit SoundFont overrides unchanged.
- Keep archive access, extraction, and MIDI rendering off the UI thread.
- Target a 256 MiB disk cache, protecting pending and playing files even if that temporarily exceeds the target; strictly cap reusable rendered-MIDI PCM at 24 MiB.
- Never retain a whole encoded non-MIDI track in the reusable music RAM cache.
- No new runtime dependencies.
- Do not run or publish a release workflow as part of this plan.

---

## File Map

- `src/couch_doom/archive.py`: describe and stream data from standalone WAD lumps, PK3 members, and WADs embedded in PK3s; retain existing byte-based access for small metadata reads.
- `src/couch_doom/music.py`: classify tracks from prefixes, retain MIDI bytes only for MIDI/MUS rendering, and store only stream-cache paths for other formats.
- `src/couch_doom/music_cache.py` (new): selection-manifest and bounded stream-payload disk caches, atomic population, cancellation and pruning.
- `src/couch_doom/cache_paths.py` (new): shared per-platform cache root used by both music and existing asset cache.
- `src/couch_doom/asset_cache.py`: import the shared cache-root helper without changing its JSON asset format.
- `tests/smoke.py`: synthetic WAD/PK3 fixtures and assertions for source streaming, cache hits, cancellation, and unchanged track selection.
- `README.md`, `packaging/How to use.txt`: distinguish the persistent music cache from the UI-asset cache and document its location/cleanup.

## Existing asset-cache flow and music alignment

The title-asset path in `ui._load_extras` follows this order: unpack and resolve inputs → derive `asset_cache.key_for` → try `asset_cache.get` → on miss find art/logo/readme/ENDOOM and optional startup art → `asset_cache.put` → return raw extracted values. UI conversion then builds Pygame surfaces, keeping title-art surfaces in a small `OrderedDict` LRU. Separately, `ui._warm_cache` visits presets breadth-first from the current selection, then calls persistent-cache prune and missing-key invalidation.

Music should keep the same persistent-cache order without copying the image-specific prefetch behavior:

1. **Selection lookup:** resolve the same preset/input set used by the music finder, derive a versioned key using `asset_cache.key_for` conventions, and read the selection manifest. A hit supplies the selected source descriptor (or cached no-track result), avoiding archive discovery.
2. **Selection miss:** run the existing precedence-ordered finder using lightweight source descriptors/prefixes, then atomically store the selected descriptor or no-track result. This mirrors asset-cache `get → find/extract → put`.
3. **MIDI preparation:** read selected MIDI/MUS bytes, convert/render with the existing SoundFont choice, then insert PCM into the 24 MiB in-memory LRU.
4. **Stream preparation:** look up the descriptor's content identity in `music/`; on miss copy to a unique partial file, validate, atomically publish, then return the path. On hit, touch access time and return the path.
5. **Pruning:** after population, prune least-recently-used stream payloads toward 256 MiB, protecting both the newly prepared path and any pending/playing path. The cache may temporarily exceed the target while those paths are in use; prune again when they are released. Prune stale partial files separately. Invalidate selection manifests against the same active preset key set used by asset-cache warm-up. Keep payload pruning independent from manifest invalidation and from the existing 512 MiB `assets/` prune.

Unlike image warm-up, music discovery/extraction stays on-demand for the selected preset; do not breadth-first prewarm neighboring tracks. That avoids unnecessary archive reads and disk writes on slow devices. The shared cache-root helper only centralizes platform path selection; `music_cache.py` owns both its manifest and stream payload APIs, while keeping their keys, formats, limits, invalidation, and failure policies separate.

## Task 1: Add reopenable archive sources

**Files:**

- Modify `src/couch_doom/archive.py`
- Modify `tests/smoke.py`

**Interface:**

Add frozen `ArchiveSource` with `size: int`, `identity: str`, `read_prefix(limit: int) -> bytes`, and `copy_to(destination: BinaryIO, cancel: threading.Event | None = None, chunk_size: int = 262144) -> int`. The descriptor stores paths and locators only; it must not retain a live `Wad`, `Zip`, `ZipFile`, or `ZipExtFile` after `Archives.__exit__`.

Add `Wad.has_lump(name) -> bool` and `Wad.lump_source(name) -> ArchiveSource | None`; add equivalent source lookup for direct ZIP members, stem-based music members, and embedded WAD lumps. A WAD source records a file range. A direct ZIP source records the member name and CRC/size. An embedded-WAD source records the outer PK3 path, embedded member, inner lump offset, and inner lump size.

- [x] Add smoke fixtures for a standalone WAD, a PK3 music member, and a WAD embedded at the root of a PK3.
- [x] Assert that `read_prefix(12)` returns only the requested prefix and that chunked `copy_to` reproduces the fixture bytes exactly for all three source types.
- [x] Assert a cancelled copy stops at the next chunk boundary and propagates cancellation to its caller.
- [x] Implement `ArchiveSource` with a 256 KiB copy loop that checks cancellation on every chunk. Reopen source files by path; for embedded WADs, reopen the outer ZIP member and seek to the recorded WAD range.
- [x] Change embedded-WAD music lookup to use source descriptors and prefix reads, bypassing `_EMBED_LUMPS` for the selected audio payload. Keep byte reads and the existing 48 MiB metadata cache for non-music callers.
- [x] Run `python tests/smoke.py`; expect the three source-copy cases and existing smoke assertions to pass on the current OS.

## Task 2: Separate MIDI data from stream sources

**Files:**

- Modify `src/couch_doom/music.py`
- Modify `tests/smoke.py`

**Interface:**

Change `Track` to hold `kind`, `name`, the detected stream `format`, and exactly one payload: `midi_data: bytes | None` or `source: ArchiveSource | None`. `_classify` returns both the playback kind and a usable suffix/hint (`mid`, `ogg`, `mp3`, `flac`, `wav`, `it`, `xm`, `s3m`, or `mod`).

- [x] Add assertions for MIDI, MUS, OGG, MP3, FLAC, WAV, and the four tracker signatures using only their identification prefixes.
- [x] Assert stream tracks return a source descriptor and no encoded `bytes`; assert MIDI tracks return MIDI bytes and no stream source.
- [x] Replace `base.lump(n)` in default-track presence detection with `base.has_lump(n)`, so a large default track is not materialized just to check whether it exists.
- [x] Update named-lump lookup and PK3 title-name guessing to retain the selected source descriptor while preserving the current search order and DeHackEd/BEX renames.
- [x] Read full data only for MIDI/MUS. Convert MUS before rendering; retain current per-preset SoundFont choice and include its identity in the rendered PCM cache key.
- [x] Run `python tests/smoke.py`; expect the selected track and source type assertions to pass while existing preset/title discovery behavior remains unchanged.

## Task 3: Add a bounded persistent stream cache

**Files:**

- Create `src/couch_doom/cache_paths.py`
- Create `src/couch_doom/music_cache.py`
- Modify `src/couch_doom/asset_cache.py`
- Modify `src/couch_doom/music.py`
- Modify `tests/smoke.py`

**Interfaces:**

- `cache_paths.cache_dir() -> Path` returns the existing platform-specific `CouchDoom` cache root.
- `music_cache.cache_stream(source: ArchiveSource, suffix: str, cancel: threading.Event, protected: Collection[Path] = ()) -> Path` returns a complete file under `<cache root>/music/` while preserving paths in use.
- `music_cache.prune(protected: Collection[Path] = ()) -> None` evicts least-recently-used stream files toward 256 MiB while skipping newly prepared, pending, and playing paths. Protected files can temporarily put the cache over target; pruning runs again when paths are released.

- [x] Add tests that the same source identity reuses one complete cache file and a changed source stat/locator receives a distinct path.
- [x] Add tests that cancellation removes `.part` files, completed files have the expected length, an oversized active stream remains available while in use and is eligible for eviction after release, and pruning leaves protected paths untouched.
- [x] Extract only platform cache-root selection from `asset_cache.cache_dir()` into `cache_paths.cache_dir()`; keep `asset_cache.cache_dir()` as a delegating compatibility function so its JSON storage path does not change. Preserve `asset_cache.key_for`, JSON encoding, `get`/`put`, atime touch, 512 MiB asset pruning, and `invalidate_missing` behavior.
- [x] Implement selection-manifest `get`/`put`/`invalidate_missing` functions in `music_cache.py`, following `asset_cache` key lookup and missing-key invalidation semantics: versioned JSON, tolerant corrupt-entry handling, and cached negative results. Write manifests atomically because a torn index must not cause repeated scans or break startup.
- [x] Key selection manifests by the existing asset-cache preset/input key, finder version, and every actual music-finder input path/stat. Store selected kind/format/name plus a serializable source descriptor, or an explicit no-track result; rebuild corrupt or version-mismatched entries.
- [x] Add smoke coverage that a warm manifest skips archive discovery, changed input stats select a new manifest, and missing music is cached as a negative result.
- [x] Implement chunked writes to a unique `.part` file, cancellation checks, byte-count validation, and atomic publication only after the complete file is ready. Remove the caller's partial file on cancellation/failure; prune abandoned `.part` files only after they are 24 hours old so a second running app instance is not interrupted.
- [x] Use the source identity from Task 1 as the cache key; include the detected format suffix so Pygame receives a recognizable filename.
- [x] Keep payload identity and discovery identity distinct: payload keys identify one archive member/lump; manifest keys identify a preset plus its ordered input files and finder version. Reuse cached selection only when all manifest inputs still match. Use the same preset fields and path/stat conventions as `asset_cache.key_for`, adding only the finder version.
- [x] On cache-write failure, log the reason and use the existing in-memory path only if the encoded track is at most 8 MiB; otherwise mark the preview unavailable without affecting launcher operation.
- [x] Change `Prepared` so stream entries hold a cache `Path`, not encoded bytes. Keep rendered MIDI PCM in the LRU with a strict 24 MiB limit; evict even when the newest PCM entry alone exceeds the limit.
- [x] Pass the stream-cache path to `pygame.mixer.music.load()`; keep the current memory-backed path only for the bounded fallback. Protect the returned pending path before pruning, then the currently loaded stream file until replacement/unload; prune again after release.
- [x] Run `python tests/smoke.py`; expect manifest hit/miss/invalidation, stream-cache hit, cancellation, pruning, and prepared-path assertions to pass.

## Task 4: Verify end-to-end behavior and document caches

**Files:**

- Modify `tests/smoke.py`
- Modify `README.md`
- Modify `packaging/How to use.txt`

- [x] Build a synthetic preset with MIDI in a WAD and OGG in a PK3; assert MIDI still reaches the renderer as bytes and OGG reaches playback as a path beneath the music cache.
- [x] Repeat stream preparation in a fresh worker invocation; assert it returns the existing cache path without copying source bytes or scanning archives.
- [x] Verify a missing/unwritable cache logs a playback diagnostic but does not raise from the UI update loop.
- [x] Verify music-manifest invalidation follows the active preset key set used by asset-cache warm-up, without deleting stream payloads still addressable by content identity; payload pruning remains size/atime-based and independent.
- [x] Document that UI assets remain under `assets/`, music files live under `music/`, and the user may clear that folder while CouchDoom is closed.
- [x] Run `python -m pyflakes src tests` and `python tests/smoke.py`; expect clean lint and the smoke suite to pass.
- [ ] Review the diff and commit the implementation only after the user has had a chance to inspect the plan.
