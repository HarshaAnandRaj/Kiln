# Debugging Kiln (for humans)

## 30-second check (do this first)

1. Server running? `curl http://127.0.0.1:8000/healthz` → `{"ok":true}`.
   If not: `kiln-server --port 8000` or `docker compose up`.
2. In Blender Kiln panel: press **Test**. It tells you latency + how to fix.
   - `Can't reach …/healthz` → wrong Server URL or firewall. URL looks like `ws://127.0.0.1:8000` (same LAN IP on both machines, not localhost across machines).
3. Both Blenders: SAME Server + SAME Room, DIFFERENT Names → Connect.
4. Move a cube. Counters `↑ ↓` should tick, `seq` should grow.

## Where to look

| Symptom | Check | Fix |
|---|---|---|
| `Server unreachable` | Test button message | Start server, fix URL |
| Connected but nothing moves | `seq` frozen, `↑0` | You are editing a locked object (red banner) → Unlock / pick another |
| `Lock denied — held by X` | Users list | Ask X to Unlock Selected |
| `mesh_too_large` | Last error | Decimate <50k verts or Push Snapshot |
| `rate_limited` | log | Slow down / disable runaway script |
| Objects duplicate | kiln_id missing | Reconnect triggers `ensure_ids` + snapshot resync |
| Split-brain after wifi drop | status `retry in 5s` | Auto-reconnects + replays from `last_seq`. If weird: Pull Snapshot |

## Debug endpoints (no Blender needed)

- `GET /healthz` → version
- `GET /v1/debug/rooms` → rooms, headcount, seq
- `GET /v1/rooms/{room}/debug` → users, locks, last 20 ops (kind only, no verts), hints
- `GET /v1/rooms/{room}/ops?since=N` → replay

Example: `python examples/debug_probe.py --server ws://127.0.0.1:8000 --room demo`

## Logs

- Blender: Kiln panel → Troubleshooting → **Export Log** → `kiln-debug.txt` (status, counters, ring log). Toggle **Show Log** (Scene prop `kiln_show_log`) for live view.
- Server: stdout `[INFO] kiln: join room=…` / `leave` / `ws error`. Run with `KILN_DATA=/data kiln-server --port 8000 2>&1 | tee kiln-server.log`.
- Filing an issue? Attach BOTH: `kiln-debug.txt` + server log + room debug JSON.

## Headless repro (no Blender)

`examples/debug_probe.py` does healthz → debug/rooms → WS hello → op → presence → prints a report. Use it in CI or to prove the network path works before opening Blender.
