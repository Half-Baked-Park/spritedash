# Spritedash

Live-sync pixel-art textures between **Aseprite** and **Blender**. Paint in Aseprite and
watch it update on your 3D model in real time — no exporting or reloading. Also sends a
mesh's UV layout to Aseprite as a paint guide, and sets up grid-scaled pixel-art
references in the viewport.

> **Spritedash is a maintained fork of [Pribambase](https://github.com/AlienPolygon/pribambase)
> by lampysprites.** The original's distribution went offline and its code relied on Blender's
> removed `bgl` module, so it no longer loaded on modern Blender. Spritedash updates it to run
> on Blender 5.x. All credit for the original design and implementation goes to lampysprites.

## License

**GPL-3.0-or-later** — same as the original Pribambase. See [`COPYING`](./COPYING).

- Original work © 2021 lampysprites.
- Modifications © 2026 Half-Baked-Park.

## Installation

Two parts that talk over a local WebSocket (default `localhost:34613`) — install **both**:

### Blender add-on
1. `Edit > Preferences > Add-ons > Install from Disk…` → pick `spritedash_blender.zip`.
2. Enable **Spritedash**.
3. Open the **Spritedash** panel in the sidebar (`N`) of the **3D Viewport**
   (Connection + Send UV + Reference) or the **Image/UV Editor** (Connection + Sprite).

### Aseprite extension
1. `Edit > Preferences > Extensions > Add Extension…` → pick `spritedash.aseprite-extension`.
2. Connect via **`File > Sync`**.

**Order matters:** start the Blender server first (Spritedash panel → **Connect**),
then connect from Aseprite (`File > Sync`).

## Changes from upstream Pribambase

- Ported `bgl` (removed in Blender 3.4+) to the modern `gpu` module — offscreen render +
  `read_color` readback for *Send UV*.
- Builtin shader name `2D_UNIFORM_COLOR` → `UNIFORM_COLOR` (Blender 4.0+).
- Bundled `aiohttp` + dependencies as wheels for Blender's Python 3.13 (Windows x64).
- Unified the UI into a single **Spritedash** sidebar panel (Sprite ops in the Image Editor,
  References in the 3D Viewport, connection in both) — replacing the old Sync panel and the
  Sprite header menu.
- Renamed the project and its Blender/Aseprite identifiers to Spritedash.
- **Fixed a hard crash on disconnect and on system sleep.** The asyncio kick timer walked
  `asyncio.all_tasks()` thousands of times a second; when a dropped connection or a wake-from-sleep
  killed tasks en masse, it walked freed weakrefs and took an access violation inside the Python DLL
  — Blender went down with no traceback. See [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md).
- **Fixed a second crash, in the modal detour.** `ModalExecuteMixin` called `modal_handler_add()`
  from `execute()` — an invoke()-only API — leaving a half-formed modal handler on the window for
  Blender to trip over later. Upstream's `skip_modal` escape hatch ("might fix some crashes") is now
  on by default.
- **Fixed sync silently dying after a reconnect.** The link came back up but painting did nothing:
  the sprite's `"change"` listener was never re-attached, and Blender was left holding stale pixels
  because the texture-list handler skipped its initial push whenever the sprite was already known.
- *Send UV* is now available in the **3D Viewport** too, targeting whatever document Aseprite has
  open (upstream only offered it in the Image Editor, where it needs an open texture).
- *Send UV* defaults to a 2048 render with 1px lines, which lands 1:1 on screen pixels at the 800%
  zoom pixel art is worked at.

## Documentation

- [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) — module map, wire protocol, data flow, and the
  event-loop constraints you need to know before touching `async_loop.py`.

## Acknowledgements

- Original tool: **Pribambase** by lampysprites — <https://github.com/AlienPolygon/pribambase>
- Async loop handling is based on the [Blender Cloud Add-on](https://cloud.blender.org/).
