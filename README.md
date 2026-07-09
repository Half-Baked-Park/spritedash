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
- Modifications © 2026 `<YOUR NAME / HANDLE>`.

## Installation

Two parts that talk over a local WebSocket (default `localhost:34613`) — install **both**:

### Blender add-on
1. `Edit > Preferences > Add-ons > Install from Disk…` → pick `spritedash_blender.zip`.
2. Enable **Spritedash**.
3. Open the **Spritedash** panel in the sidebar (`N`) of the **3D Viewport**
   (Connection + Reference) or the **Image/UV Editor** (Connection + Sprite).

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

## Acknowledgements

- Original tool: **Pribambase** by lampysprites — <https://github.com/AlienPolygon/pribambase>
- Async loop handling is based on the [Blender Cloud Add-on](https://cloud.blender.org/).
