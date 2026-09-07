# Roadmap

## v0.1.0-alpha (this session — usable)
- [x] Protocol SPEC v0.1 + JSON schema
- [x] Server: rooms, WS broadcast, locks, presence, comments, snapshot, op replay, persistence
- [x] Addon: stdlib WS, scan/diff/apply, transform+object sync, mesh.replace (capped), locks UI, presence UI, comments, snapshot push/pull
- [x] Tests: server protocol + replay, addon fingerprint/pack (no Blender needed via stub)
- [x] Docker + compose, examples

## v0.2 — Mesh-grade (next)
- Per-vertex delta (`mesh.delta`: changed indices only), bmesh edit-mode streaming
- Undo-coalescing (wrap apply in `bpy.ops.ed.undo_push`)
- Viewport gaze + 3D cursor share, follow mode
- Strict-lock rooms, kick/ban, room passwords UI

## v0.3 — Production workspace
- Branches: `main` + per-user branch, diff (added/removed/moved), 3-way merge UI
- Asset browser integration, collection-level perms
- Accounts (OIDC), E2EE rooms (MLS-ish), S3 snapshots
- Headless render-farm snapshot hook

## v1.0 — Scale
- 50-user room test (locust), Redis pub/sub for multi-node server
- CRDT for verts (Yjs port or Automerge), conflict-free sculpt
- Voice (WebRTC sidecar), audit log export
