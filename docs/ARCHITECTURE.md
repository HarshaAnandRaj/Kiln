# Architecture — Kiln v0.1

```
 Blender A (addon) ─┐
                     ├─ WS JSON ops ─► FastAPI Room ─► broadcast + op log + snapshot
 Blender B (addon) ─┘                     ▲
                                          │ REST: /snapshot /ops?since=
```

## Components

### Addon (`addon/kiln/`, GPL-3.0)

- `net_ws.py`: stdlib-only WebSocket client (socket+ssl+thread). Why not `websockets`? Blender's embedded Python often lacks pip; stdlib guarantees install works. Thread reads frames → `queue.Queue`; main timer (0.2s) drains on Blender main thread (all `bpy` calls must be main-thread).
- `core_ids.py`: `get_or_create_kiln_id(obj)` stores UUID in `obj["kiln_id"]`. Stable across rename/parent. On file load, ensure all objects have IDs.
- `sync.py`: `scan_scene() → {kiln_id: fingerprint}`, diff vs cache → emit `object.upsert|transform|object.remove`. `apply_op(op)` with `SUPPRESS` flag to avoid echo loops. LWW: higher `seq` wins; per-field merge for transform.
- `mesh_sync.py`: pack `mesh.vertices[].co` + `polygons[].vertices` (+ loop normals skipped v0.1). Cap 50k verts, throttle 2 Hz. Push on `edit-mode exit` + manual button, not every timer tick.
- `ui.py`: N-panel `View3D > Kiln`, operators connect/disconnect/lock/push/pull/comment. User list with colors.
- State machine: `OFFLINE → CONNECTING → SYNCING (snapshot+replay) → LIVE → RECONNECTING`.

### Server (`server/src/kiln_server/`, Apache-2.0)

- `main.py`: FastAPI app. REST: health, snapshot get/post, ops replay. WS: `/v1/rooms/{room}/ws`.
- `rooms.py`: `RoomManager { rooms: {name: RoomState} }`. `RoomState`: `seq:int`, `ops:deque[dict]` (cap 10k), `objects:{kiln_id:last_op}`, `locks:{kiln_id:user}`, `presence:{user:presence}`, `comments:[]`, `snapshot:{seq,scene}|None`. All mutations under per-room `asyncio.Lock`.
- `models.py`: Pydantic v2 envelope validation. Unknown kinds rejected.
- `store.py`: JSONL append (`data/{room}.jsonl`) + `snapshot.json` atomic write. Crash recovery on boot.
- Auth v0.1: room password via `?token=` vs stored (first creator sets). No user accounts yet (v0.3).

### Why authoritative + LWW, not CRDT yet?

Mesh-level CRDT (Yjs-style) is correct long-term but heavy for Blender meshes. v0.1 LWW + soft locks is predictable, debuggable, and good enough for 2–10 users. Op log gives audit + replay. v0.2 adds per-vertex delta + undo coalescing.

### Threading / bpy safety

- NEVER call `bpy` from net thread. Net thread → queue → `bpy.app.timers` callback applies.
- `bpy.app.handlers`: `depsgraph_update_post` sets `dirty=True`; timer does the scan (cheap fingerprint: loc/rot/scale/name/visible + mesh `update_tag` counter).

### Failure modes

- Split-brain on net partition: server seq wins; client replays on reconnect.
- Large mesh: rejected with `mesh_too_large`, UI prompts decimate or snapshot.
- Blender undo: v0.1 coalesces — undo triggers rescan → new ops (no special OT). Documented limitation.

See `SPEC-v0.1.md` for wire, `ROADMAP.md` for what's next.
