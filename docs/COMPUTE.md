# Shared Compute — same-session farm (v0.2-alpha)

Only PCs in the SAME room share. No outside farm, no accounts. Workers already
have the scene via live sync, so jobs carry params only — no .blend upload.

## Use it (seamless)

1. 2+ Blenders → same Server + same Room, different Names → Connect.
2. Each farmer: Kiln panel → Shared Compute → **Share my CPU/GPU** (ON).
3. One PC: **Render Frames 1-4** / **Render Tiles** / **Bake on fastest PC**.
4. Watch progress `done/total` + `Working: … %`. Others auto-claim when idle.
5. v0.2 artifacts are checksums (simulated pixels). Real EXR/PNG via blob store lands in v0.3.

## Smart allocation

`score = 10*cpu + 20 (gpu) + 5*mem/8 − 30*load − rtt/50 − 1000 (version mismatch / not sharing / stale>30s)`.
- Frame/tile: whoever claims gets best waiting task; expired leases (60-120s) + disconnects requeue automatically.
- Bake: single task, only the max-score sharer may claim; others get `job.wait`.
- Blender major.minor must match `blend_version` or veto.

## Debug

- `GET /v1/rooms/{r}/jobs` + `/jobs/{id}` — tasks, workers, pct.
- `GET /v1/debug/rooms` now shows `workers/jobs` counts.
- WS: `worker.list`, `job.posted/task/wait/progress/result/cancelled`.
- Headless: `python examples/compute_farm_demo.py --server ws://127.0.0.1:8000 --room demo` (2 fake workers + 1 frame job end-to-end).
- Safety: room members only, `--disable-autoexec` recommended, don't farm with strangers (arbitrary .blend = arbitrary code until Docker sandbox in v1.0).
