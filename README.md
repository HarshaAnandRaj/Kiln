# Kiln — Collaborative Workspace for Blender

**Google-Docs-style live editing for Blender. Real rooms, presence, locks, comments, and history — self-hosted, open-source.**

> Status: `v0.1.0-alpha` — genuinely usable for 2–10 artists in one room: live object/transform sync, per-object locks, presence/selection, comments, snapshots.

## Why Kiln?

Blender is single-player. Production is not. Existing sync scripts blast whole `.blend` files or break on conflicts. Kiln syncs **ops, not files**:

- Op-based sync at Object + Transform + Mesh level (low latency, order-guaranteed)
- Authoritative server with sequence numbers (last-writer-wins + soft locks)
- Stable IDs via `obj["kiln_id"]` so rename/parent don't fork
- Stdlib-only Blender addon — no pip hell inside Blender
- Self-host in 1 command: `docker compose up`

## Quickstart (2 min)

### 1. Run server

```powershell
pip install -e ./server
kiln-server --host 127.0.0.1 --port 8000
# -> ws://127.0.0.1:8000/v1/rooms/{room}/ws
# -> http://127.0.0.1:8000/healthz
```

Or Docker:

```powershell
docker compose up --build
```

### 2. Install addon in Blender 4.2 LTS+

1. Zip `addon/kiln/` → `kiln.zip` (or use Releases).
2. Blender → Edit → Preferences → Add-ons → Install from Disk → select `kiln.zip`.
3. Enable `Kiln Collaborative Editing`.
4. Sidebar (N) → Kiln → Server `ws://127.0.0.1:8000`, Room `demo`, Name `anand` → Connect.

Open a second Blender, same room, different name. Move a cube. It moves on both.

### 3. Lock, comment, snapshot

- Select object → `Lock` to claim it (others get read-only warning).
- `Add Comment @ 3D Cursor` to pin a note.
- `Push Snapshot` before a risky edit, `Pull Snapshot` to restore.

## Repo layout

```
Kiln/
  addon/kiln/        # Blender addon (GPL-3.0-or-later, bpy requirement)
    __init__.py      # bl_info + registration
    core_ids.py      # stable kiln_id management
    net_ws.py        # stdlib-only WS client (no deps in Blender)
    proto.py         # message builders/validators (mirrors protocol/)
    sync.py          # scene scan → ops, ops → scene
    mesh_sync.py     # mesh vert/loop/polygon pack/unpack
    ui.py            # N-panel, operators
    presence.py      # user list + colors
  server/            # FastAPI sync server (Apache-2.0)
    src/kiln_server/
      main.py        # REST + WS
      rooms.py       # RoomState, op log, locks, presence
      models.py      # Pydantic v2 messages
      store.py       # JSONL + snapshot persistence
  protocol/
    SPEC-v0.1.md     # wire spec (normative)
    schema.json      # JSON Schema for validators
  docs/
    ARCHITECTURE.md
    ROADMAP.md
    CONTRIBUTING.md
  examples/
    two_cubes_sync.py  # headless protocol demo (no Blender needed)
```

## Protocol v0.1 (summary)

`WS /v1/rooms/{room}/ws?user={name}` — JSON messages, server assigns `seq`.

Client → Server: `hello | op | presence | lock | unlock | comment | snapshot_push | snapshot_request`
Server → Client: `welcome | op | presence | lock_granted | lock_denied | comment | snapshot | error`

Op kinds (v0.1): `object.upsert | object.remove | transform | mesh.replace | material.assign | collection.link`

See [`protocol/SPEC-v0.1.md`](protocol/SPEC-v0.1.md) — normative.

## Production notes (to stay usable)

- **Echo suppression:** every op has `op_id` (uuid). Server echoes to all including sender; sender drops `op_id` it sent.
- **Throttle:** transforms debounced to 10 Hz per object; mesh.replace max 2 Hz + 50k vert cap (larger → `error mesh_too_large`, use snapshot).
- **Locks are soft:** holder wins on conflict; others see banner + viewport color. Server enforces `lock_denied` if already held.
- **Reconnect:** backoff 1s→10s, then `snapshot_request` + replay from `last_seq`.
- **History:** server keeps last 10k ops (`GET /v1/rooms/{room}/ops?since={seq}`) + latest snapshot.

## Licensing (important for Blender)

- `addon/` → **GPL-3.0-or-later** (required: Blender `bpy` API is GPL).
- `server/`, `protocol/`, `examples/` → **Apache-2.0**.
- See `LICENSE-ADDON`, `LICENSE-SERVER`, `NOTICE`.

## Roadmap

- v0.2: mesh delta (vertex-level CRDT), undo-coalescing, viewport gaze share
- v0.3: branches/diff, asset browser link, WebRTC voice
- v1.0: E2EE rooms, S3 snapshots, scale test 50 users

See [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Contributing

PRs welcome. Run `pytest server/tests addon/tests` before pushing. See [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md).
