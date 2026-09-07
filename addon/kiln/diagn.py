"""Kiln diagnostics: friendly hints, ring-log, connection probe. No bpy at import."""
from __future__ import annotations
import json
import time
import urllib.parse
import urllib.request
from collections import deque

ERROR_HINTS: dict[str, str] = {
    "mesh_too_large": "Mesh over 50k verts — Decimate first, or use Push Snapshot.",
    "rate_limited": "Sending too fast — slow down. Server caps 30 ops/s to protect the room.",
    "unknown_kind": "Version mismatch — update server + addon to the same release.",
    "lock_denied": "Locked by someone else — ask them to Unlock.",
    "bad_json": "Network glitch — retry. If it repeats, Test Connection.",
    "bad_room": "Room name invalid — use letters/numbers/-/_ .",
    "stale": "You are behind — Pull Snapshot, then rejoin.",
    "upgrade_required": "Addon too old — reinstall kiln.zip from this server's release.",
    "internal": "Server hiccup — retry, then export logs if it repeats.",
}

LOG_LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")


class RingLog:
    """Thread-safe-ish ring buffer. Pure python so tests run headless."""
    def __init__(self, maxlen: int = 500):
        self.buf: deque[str] = deque(maxlen=maxlen)

    def add(self, level: str, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.buf.append(f"{ts} [{level}] {msg}")

    def last(self, n: int = 100) -> list[str]:
        return list(self.buf)[-n:]

    def clear(self):
        self.buf.clear()

    def dump(self) -> str:
        return "\n".join(self.buf)


def hint_for(code: str) -> str:
    return ERROR_HINTS.get(code, "Retry. If it repeats, use Test Connection + Export Log.")


def http_base_from_ws(ws_base: str) -> str:
    u = urllib.parse.urlparse(ws_base.strip())
    scheme = "https" if u.scheme == "wss" else "http"
    host = u.hostname or "127.0.0.1"
    port = u.port or (443 if scheme == "https" else 80)
    return f"{scheme}://{host}:{port}"


def probe_server(ws_base: str, timeout: float = 6.0) -> dict:
    """Headless-friendly connection test: healthz + debug/rooms. Returns report dict."""
    base = http_base_from_ws(ws_base)
    t0 = time.time()
    try:
        with urllib.request.urlopen(base + "/healthz", timeout=timeout) as r:
            health = json.loads(r.read())
        dt_ms = int((time.time() - t0) * 1000)
    except Exception as e:
        return {"ok": False, "stage": "healthz", "latency_ms": -1,
                "message": f"Can't reach {base}/healthz: {e}",
                "fix": "Is kiln-server running? Try `kiln-server --port 8000` or `docker compose up`. Check firewall."}
    try:
        with urllib.request.urlopen(base + "/v1/debug/rooms", timeout=timeout) as r:
            dbg = json.loads(r.read())
        rooms = dbg.get("rooms", [])
    except Exception:
        rooms = []
    return {"ok": True, "stage": "ok", "latency_ms": dt_ms,
            "message": f"Server {health.get('version')} reachable in {dt_ms}ms. Rooms live: {len(rooms)}.",
            "fix": "", "rooms": rooms,
            "next": "In Blender: same Server URL + same Room on both machines, different Names, then Connect."}
