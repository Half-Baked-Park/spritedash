# Spritedash architecture

Two processes joined by one WebSocket. **Blender is the server, Aseprite is the client** — the
Blender side stays up for a long time while Aseprite comes and goes, so that direction is the
natural one.

```
┌───────────────────────── Blender ──────────────────────────┐      ┌────────── Aseprite ──────────┐
│                                                            │      │                              │
│  ui_2d.py / ui_3d.py   — operators + sidebar panels        │      │  Sync.lua     — socket + UI  │
│         │                                                  │      │      │                       │
│  addon.py (Addon singleton: prefs / state / server / …)    │      │  Commands.lua — menu entry   │
│         │                                                  │      │  Settings.lua — settings dlg │
│  sync.py  — aiohttp WebSocket server :34613 ───────────────┼──ws──┤      │                       │
│         │                                                  │      │      │                       │
│  messaging/  — binary protocol (encode ↔ handle)           │      │  string.pack / unpack        │
│         │                                                  │      │                              │
│  async_loop.py — pumps the asyncio loop from a bpy timer   │      │                              │
└────────────────────────────────────────────────────────────┘      └──────────────────────────────┘
```

## Module map (Blender side)

| File | Role |
|---|---|
| `__init__.py` | `register()`, `bl_info`, injects bundled wheels into `sys.path`, installs blender handlers (load_pre/post, depsgraph) |
| `addon.py` | `Addon` singleton — the single access point for `prefs` / `state` / `server` / `handlers` |
| `settings.py` | `SB_Preferences` (port, autostart, UV color/thickness/scale, `skip_modal`) |
| `sync.py` | `Server` — the aiohttp WebSocket server: accept, receive loop, shutdown. Start/stop/texture-list operators |
| `async_loop.py` | The glue that runs an asyncio loop inside Blender's main loop. **See "Event loop" below** |
| `messaging/__init__.py` | Byte-level primitives (`take_*` / `add_*`) and the `Handler` / `Handlers` dispatcher |
| `messaging/encode.py` | **Outgoing** message encoders (Blender → Aseprite) |
| `messaging/handle.py` | **Incoming** message handlers (Aseprite → Blender) |
| `ui_2d.py` | Image Editor operators — Send UV, New/Open/Edit/Replace Sprite |
| `ui_3d.py` | 3D Viewport operators (reference images) and both sidebar panels |
| `util.py` | `refresh()` (tag_redraw), `image_name()`, `ModalExecuteMixin`, `update_image`, `report` |

## Wire protocol

Little-endian binary. Every message starts with a **1-byte ID**; variable-length fields carry a
**u32 length prefix** (`add_data` / `take_data`). The Aseprite side speaks the same convention via
`string.pack("<Bs4s4", ...)`.

### Blender → Aseprite (`encode.py`)

| ID | Name | Payload | Meaning |
|---|---|---|---|
| `[` | batch | `count:u16` + `data*` | Several messages in one frame |
| `L` | texture_list | `string*` | Textures this blend file holds (populates Aseprite's dropdown) |
| `M` | uv_map | `opacity:u8, w:u16, h:u16, layer:str, sprite:str, pixels` | **Send UV** — UV edges rendered to RGBA, dropped in as a reference layer |
| `I` | image | `w:u16, h:u16, name:str, pixels` | Hand a Blender image to Aseprite (Edit / Edit Copy) |
| `S` | sprite_new | `mode:u8, w:u16, h:u16, name:str` | Create a new document |
| `O` | sprite_open | `name:str` | Open a file |
| `F` | sprite_focus | `name:str` | Focus that document's tab (usually batched with `M`) |

### Aseprite → Blender (`handle.py`)

| ID | Handler | Payload | Meaning |
|---|---|---|---|
| `[` | `Batch` | `count:u16` + `data*` | Unpacked recursively |
| `I` | `Image` | `w:u16, h:u16, name:str, pixels` | **The hot path** — painted pixels overwrite the Blender image |
| `N` | `NewImage` | ″ | Create the image if missing, then behave like `I` |
| `L` | `TextureList` | (none) | Request a fresh texture list |
| `C` | `ChangeName` | `old:str, new:str` | Aseprite saved under a new name → update `sb_source` / `filepath` |

### Image identity — `util.image_name()`

The **only** key that decides whether both sides mean the same image:

```
img.sb_source   (custom prop spritedash sets: absolute path or name)
  → img.filepath   (when not packed; // relative paths are made absolute)
    → img.name     (otherwise)
```

`sb_source` is a StringProperty registered on `bpy.types.Image` (`__init__.py`). It is saved into
the .blend, so a file reopened tomorrow still pairs up with the same Aseprite documents.

## Data flow

### Painting in Aseprite → texture updates in Blender (the hot path)

```
Aseprite: sprite change observer (Sync.lua)
  └ ws:sendBinary( messageImage{...} )        -- 'I' or 'N'
      └ Blender: the `async for` loop in Server._receive
          └ addon.handlers.process(data)      -- dispatch on the ID byte
              └ handle.Image.execute()
                  └ util.update_image()  →  bpy.ops.spritedash.update_image()
                      └ SB_OT_update_image.modal_execute()
                          ├ img.scale() if the size changed
                          ├ uint8 → float32, flip the y axis
                          ├ img.pixels.foreach_set(pixels)
                          └ img.update_tag() + util.refresh()   -- redraw
```

### Send UV → a paint guide in Aseprite

```
SB_OT_send_uv.execute()   (Image Editor or 3D Viewport sidebar)
  ├ pick the destination
  │   ├ 'active'  → send sprite="". Aseprite draws into whatever document is open.
  │   │             Blender does not need to know which image that is. Default for the 3D Viewport.
  │   └ 'texture' → target_image(): the image editor's image, else the texture paint canvas.
  │                 Sends sprite=image_name(img), batched with sprite_focus to switch tabs.
  ├ list_uv()            -- collect UV edges of the selected faces via bmesh (deduplicated)
  ├ render LINES into a GPUOffScreen → fb.read_color() readback
  └ encode.uv_map() → server.send()
      └ Aseprite: handleUVMap lays the image into the configured layer (scaled to the sprite)
```

> The 3D Viewport panel passes `destination='active'` on purpose. Upstream's default, `'texture'`,
> reads the image editor's open image — in the 3D Viewport there is none, so it would just fail.
> Spritedash syncs with whatever Aseprite has open anyway, so "the document Aseprite is looking at"
> is the right target there.

### Keeping the texture list fresh

`sb_on_depsgraph_update_post` watches `dg.id_type_updated('IMAGE')` and only sends `L` when the hash
of the image-name set actually changed — otherwise it would fire on every depsgraph tick.

## Event loop — the part to be careful with

Blender runs its own main loop; aiohttp wants an asyncio loop. To keep both on one thread, **a
Blender timer kicks the asyncio loop one tick at a time**:

```python
# async_loop.py
def kick_async_loop():
    loop.stop()          # so the next run_forever does exactly one pass
    loop.run_forever()   # process whatever callbacks/coroutines are ready
    return 0.001         # again in 1 ms

bpy.app.timers.register(kick_async_loop, persistent=True)
```

What follows from that:

- **Coroutines run on the main thread**, since they run inside the timer callback. That is why the
  handlers can touch `bpy` data at all. On a worker thread this would die instantly.
- **Calling `bpy.ops` from a coroutine is still not proper**, and the detour upstream used to make it
  palatable was itself a crash. `util.ModalExecuteMixin` called `modal_handler_add()` from
  `execute()` — an invoke()-only API. From a timer callback there is no proper area/region context,
  so a half-formed modal handler got parked on the window and Blender tripped over it later, inside
  `wm_event_do_notifiers`, with no Python frame left on the stack. The `skip_modal` preference
  (upstream's own escape hatch, "might fix some crashes") is now **on by default**, which skips the
  detour entirely: the coroutine already runs on the main thread, so it just does the work inline.
  If you ever turn `skip_modal` back off, know that you are re-arming that crash.
- **Never call `asyncio.all_tasks()` in this kick.** It used to be here, and it crashed Blender.
  The kick runs thousands of times a second, and `all_tasks()` copies the internal weakset of tasks.
  When the connection drops or the machine wakes from sleep, tasks die and get collected en masse;
  the copy then walks freed weakrefs and takes an access violation inside `python313.dll` — Blender
  dies with no Python traceback at all. The kick does not need the task list: while the server is up
  it must keep pumping regardless.
- **Shutdown is awaited synchronously.** Once the timer is gone nobody pumps the loop, so
  `Server.stop()` drives the shutdown coroutine with `run_until_complete` before calling
  `erase_async_loop()`.

## Lifecycle

```
register()
  └ setup_asyncio_executor()          -- win32: ProactorEventLoop, stored in the module-level _loop
  └ register classes, add Image.sb_source / Image.sb_scale props
  └ timers.register(start, 0.5s)      -- a beat after startup, just in case

start()  (fires once)
  └ reference_reload_all()
  └ addon.start_server() if prefs.autostart
  └ install load_pre / load_post / depsgraph_update_post handlers

opening a .blend
  └ load_pre  → stop the server (it must not hold images from the outgoing file)
  └ load_post → reload references, restart the server if autostart

unregister()
  └ stop the server, remove timers/handlers, delete props, unregister classes
```

Connection state has two levels: `addon.server_up` (the server object exists) and `addon.connected`
(a WebSocket is attached and open). The sidebar's Off / Waiting… / Connected is exactly that pair.

## Aseprite side (`client/`)

| File | Role |
|---|---|
| `package.json` | Extension manifest; `contributes.scripts` points at `Commands.lua` |
| `Commands.lua` | Menu entry, initializes `spritedash_settings` (= `plugin.preferences`) |
| `Sync.lua` | WebSocket client, receive dispatch table, sprite change observer, status dialog |
| `Settings.lua` | Settings dialog (host / port / autostart / size limit) |

The dispatch table in `Sync.lua` maps 1:1 onto `encode.py`:

```lua
[string.byte('I')] = handleImage,     [string.byte('[')] = handleBatch,
[string.byte('M')] = handleUVMap,     [string.byte('L')] = handleTextureList,
[string.byte('S')] = handleNewSprite, [string.byte('O')] = handleOpenSprite,
[string.byte('F')] = handleFocus,
```

Sprites larger than the `maxsize` setting are not sent. The client reconnects on its own after a
drop, so the Blender server must keep listening once a client goes away.

**Reconnect is a state-restoration problem, not just a socket problem.** Two things have to happen
again or the link comes back up and silently does nothing:

- The `"change"` listener on the active sprite. It is dropped on CLOSE and re-attached on OPEN;
  OPEN calls `off()` before `on()` so a reconnect neither misses it (blender died without a clean
  close, so CLOSE never fired) nor double-registers it.
- The pixels themselves. Blender sends `L` (texture list) immediately on every connection, so
  `handleTextureList` doubles as the "just (re)connected" hook and pushes the current sprite once.
  Upstream skipped that push whenever the sprite was already in the previous `syncList` — which
  after a reconnect is precisely the case where Blender is sitting on stale pixels.

## Dependencies

`aiohttp` and its tree (`aiosignal`, `attrs`, `frozenlist`, `idna`, `multidict`, `propcache`,
`yarl`, `aiohappyeyeballs`) are **bundled as wheels** under `thirdparty/` and pushed onto `sys.path`
by `__init__.py`, because extensions.blender.org forbids installing anything at runtime. The current
wheels are **cp313 / win_amd64 only** — supporting other platforms means adding their wheels and
declaring `platforms` in the manifest.
