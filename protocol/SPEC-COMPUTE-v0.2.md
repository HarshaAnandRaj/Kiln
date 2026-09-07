# SPDX-License-Identifier: Apache-2.0
# Copyright (C) Kiln Contributors — see LICENSE-SERVER
# Kiln Shared Compute — SPEC v0.2 (same-session only)

Scope: workers = members of the SAME room WS session. No outside farm.
Leverages live sync: workers already have the scene, so no .blend upload.
Server never executes; it schedules + aggregates.

## Messages (WS, same envelope as SPEC-v0.1)

- `worker.hello {caps: {cpu:int, mem_gb:float, gpu:string|null, blender:string, share:bool, load:float}}`
  Server stores per user, rebroadcasts `worker.list` to room.
- `job.submit {job_id?, type: frame|tile|bake, params:{...}}` → server replies `job.posted {job}` + broadcasts `job.posted`.
- `job.claim {job_id}` → server replies `job.task {task}` or `job.wait`.
- `job.progress {job_id, task_id, pct:0-100}` → broadcast (for progress bars).
- `job.result {job_id, task_id, ok:bool, artifact?:{...}, log_tail?:str}` → broadcast + stored.
- `job.cancel {job_id}`

REST mirrors: `POST /v1/rooms/{r}/jobs`, `GET .../jobs`, `GET .../jobs/{id}`, `POST .../jobs/{id}/results`.

## Job types

- `frame`: params `{frame_start:int, frame_end:int, samples:int, engine:CYCLES|BLENDER_EEVEE, blend_version:str}`.
  Tasks: one per frame. Artifact: `{frame:int, png_b64_or_url:str, checksum:str}` (v0.2: checksum + size only in tests; real PNG via blob store later).
- `tile`: params `{frame:int, grid:int=2, border:float=0.05, samples, engine}`.
  Tasks: grid*grid tiles `{tx,ty,x0,y0,x1,y1}` in 0-1 UV. Artifact: `{tile, checksum}`.
- `bake`: params `{kind: physics|geometry_nodes, target_kiln_id?:str}`.
  Tasks: single task (whole bake) assigned to beefiest worker. Artifact: `{snapshot_seq:int}` (worker pushes snapshot after bake).

## Smart allocation (server, deterministic, testable)

Score(worker, task) — higher wins:
```
score = 10*cpu + (20 if gpu and job wants gpu else 0) + 5*mem_gb/8
        - 30*load - rtt_ms/50
        - 1000 if blender != job.blend_version (version mismatch veto unless no match)
        - 1000 if not share
```
- Frame/tile: greedy assign on claim (server picks best waiting task for that worker) + requeue on timeout (30s no progress) or disconnect.
- Bake: direct-assign to max score worker; others get `job.wait`.
- Same-session guarantee: only `room.connections` members with fresh `worker.hello` (<30s) eligible.

Timeouts: task lease 60s (frame), 120s (tile/bake). Heartbeat via `job.progress` renews.

## Seamless UX contract

- Toggle `Share my CPU/GPU` → sends `worker.hello share:true` once + on caps change.
- Submit → optimistic `job.posted` + progress bars grouped by worker color.
- Workers auto-claim when idle (addon timer, 1 claim per 2s max).
- Completion → `Fetch` pulls artifacts (v0.2: checksums list; real pixels in v0.3 blob store).

## Limits v0.2

- Max 32 tasks/job, max 8 workers/room, artifact payload ≤ 1 MB (checksums for now).
- No remote code exec: worker executes ONLY its local open .blend via bpy (or sim in tests).
- Blender version must match major.minor or task refused with `fix: update Blender`.
