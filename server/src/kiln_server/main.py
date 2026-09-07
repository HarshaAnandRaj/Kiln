# SPDX-License-Identifier: Apache-2.0
# Copyright (C) Kiln Contributors � see LICENSE-SERVER
"""Kiln sync server — FastAPI + WebSocket. Authoritative room sequencer."""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import time
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse

from .models import validate_op_payload
from .rooms import RoomManager
from . import store

VERSION = "0.1.0"
MIN_CLIENT = "0.1.0"

log = logging.getLogger("kiln")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] kiln: %(message)s")

app = FastAPI(title="Kiln", version=VERSION)
manager = RoomManager()

# Human-friendly error hints: code -> (what happened, what to do).
ERROR_HINTS: dict[str, tuple[str, str]] = {
    "bad_json": ("Message wasn't valid JSON.", "Check your network / update the addon. This usually means a glitch, just retry."),
    "bad_room": ("Room name is invalid.", "Use letters, numbers, - or _ (e.g. demo)."),
    "unknown_kind": ("Unknown message type.", "Update both server and addon to the same version."),
    "mesh_too_large": ("Mesh has over 50k verts.", "Decimate first, or use Push Snapshot instead of live mesh push."),
    "rate_limited": ("Sending too fast (>30 ops/s).", "Move slower / check for a runaway script. Server throttles to protect the room."),
    "stale": ("Your scene is behind the room.", "Hit Pull Snapshot, then rejoin."),
    "lock_denied": ("Object is locked by someone else.", "Ask them to Unlock, or pick another object."),
    "upgrade_required": ("Addon is too old.", "Reinstall kiln.zip from the same release as the server."),
    "internal": ("Server hiccup.", "Retry. If it repeats, export the addon log + server log and file an issue."),
}


def _now() -> float:
    return time.time()


def err_frame(room: str, code: str, detail: str = "", op_id: str | None = None) -> dict:
    hint, fix = ERROR_HINTS.get(code, ("Something went wrong.", "Retry. If it repeats, Test Connection in the Kiln panel."))
    p: dict = {"code": code, "detail": detail, "hint": hint, "fix": fix}
    if op_id:
        p["op_id"] = op_id
    return {"t": "error", "room": room, "from": "server", "ts": _now(), "payload": p}


async def _broadcast(room_name: str, frame: dict, exclude: WebSocket | None = None):
    room = await manager.get(room_name)
    dead = []
    for ws in list(room.connections):
        if ws is exclude:
            continue
        try:
            await ws.send_text(json.dumps(frame))
        except Exception:
            dead.append(ws)
    for ws in dead:
        room.connections.discard(ws)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "version": VERSION}


@app.get("/v1/rooms/{room}/snapshot")
async def get_snapshot(room: str):
    st = await manager.get(room)
    async with st.lock:
        snap = st.snapshot
    if snap is None:
        snap = store.load_snapshot(room.lower())
        if snap is not None:
            async with st.lock:
                st.snapshot = snap
                st.seq = max(st.seq, int(snap.get("seq", 0)))
    if snap is None:
        return JSONResponse({"room": room, "snapshot": None, "seq": st.seq})
    return {"room": room, "snapshot": snap, "seq": st.seq}


@app.post("/v1/rooms/{room}/snapshot")
async def post_snapshot(room: str, body: dict):
    st = await manager.get(room)
    scene = body.get("scene", {})
    async with st.lock:
        st.seq += 1
        snap = {"seq": st.seq, "scene": scene, "server_ts": _now()}
        st.snapshot = snap
    store.save_snapshot(room.lower(), snap)
    frame = {"t": "snapshot", "room": room, "from": body.get("from", "server"),
             "ts": _now(), "payload": snap}
    await _broadcast(room, frame)
    return snap


@app.get("/v1/rooms/{room}/ops")
async def get_ops(room: str, since: int = 0, limit: int = 500):
    st = await manager.get(room)
    ops = await st.ops_since(since, min(limit, 1000))
    return {"room": room, "seq": st.seq, "ops": ops}


@app.get("/v1/debug/rooms")
async def debug_rooms():
    """List rooms with headcount — for admins and the addon's Test Connection."""
    out = []
    for name, st in list(manager._rooms.items()):
        async with st.lock:
            out.append({"room": name, "seq": st.seq, "connections": len(st.connections),
                        "users": sorted(st.presence.keys()), "locks": len(st.locks),
                        "ops": len(st.ops), "comments": len(st.comments),
                        "has_snapshot": st.snapshot is not None})
    return {"version": VERSION, "rooms": out}


@app.get("/v1/rooms/{room}/debug")
async def debug_room(room: str):
    """Per-room tail for debugging: last ops, locks, users. No mesh verts (summary only)."""
    st = await manager.get(room)
    async with st.lock:
        tail = list(st.ops)[-20:]
        summary = [{"seq": o.get("seq"), "from": o.get("from"),
                    "kind": (o.get("payload") or {}).get("kind"),
                    "kiln_id": str((o.get("payload") or {}).get("kiln_id", ""))[:8]} for o in tail]
        return {"room": room, "seq": st.seq, "connections": len(st.connections),
                "users": [{"name": u, "color": st.user_colors.get(u)} for u in st.presence],
                "locks": dict(st.locks), "comments": len(st.comments),
                "snapshot_seq": (st.snapshot or {}).get("seq", 0),
                "recent_ops": summary,
                "hints": {"empty_room": "No users? Both Blenders must use the SAME server URL + room name (case-insensitive).",
                          "no_ops": "No ops yet? Move an object — transforms flush at 10 Hz."}}


@app.websocket("/v1/rooms/{room}/ws")
async def room_ws(ws: WebSocket, room: str, user: str = Query("anon"), client: str = Query("0.0.0")):
    room = room.lower()
    user = (user or "anon")[:32] or "anon"
    await ws.accept()
    st = await manager.get(room)
    st.connections.add(ws)
    log.info("join room=%s user=%s conns=%d", room, user, len(st.connections) + 1)
    try:
        # Expect hello first (tolerant: proceed anyway after 5s)
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=5.0)
            try:
                hello = json.loads(raw)
            except ValueError:
                hello = {}
            color = (hello.get("payload") or {}).get("color", "#3fa9f5")
            last_seq = int((hello.get("payload") or {}).get("last_seq", 0))
            st.user_colors[user] = color
        except asyncio.TimeoutError:
            color, last_seq = "#3fa9f5", 0
            st.user_colors.setdefault(user, color)

        async with st.lock:
            users = [{"name": u, "color": st.user_colors.get(u, "#3fa9f5")} for u in st.presence]
            users.append({"name": user, "color": st.user_colors.get(user, color)})
            welcome = {"t": "welcome", "room": room, "from": "server", "ts": _now(),
                       "payload": {"you": user, "seq": st.seq, "users": users,
                                   "locks": dict(st.locks),
                                   "snapshot_seq": (st.snapshot or {}).get("seq", 0)}}
        await ws.send_text(json.dumps(welcome))

        # Replay missed ops
        if last_seq < st.seq:
            missed = await st.ops_since(last_seq)
            for m in missed:
                await ws.send_text(json.dumps(m))

        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                await ws.send_text(json.dumps(err_frame(room, "bad_json", "invalid JSON")))
                continue
            t = msg.get("t")
            payload = msg.get("payload") or {}

            if t == "op":
                if not st.check_rate(user):
                    await ws.send_text(json.dumps(err_frame(room, "rate_limited", "30 ops/s", payload.get("op_id"))))
                    continue
                ok, why = validate_op_payload(payload)
                if not ok:
                    code = why.split(":")[0]
                    await ws.send_text(json.dumps(err_frame(room, code, why, payload.get("op_id"))))
                    continue
                frame = {"t": "op", "room": room, "from": user, "ts": _now(), "payload": payload}
                stored = await st.append_op(frame)
                store.append_op(room, stored)
                await _broadcast(room, stored)
            elif t == "presence":
                async with st.lock:
                    st.presence[user] = {**payload, "color": st.user_colors.get(user), "ts": _now()}
                await _broadcast(room, {"t": "presence", "room": room, "from": user, "ts": _now(), "payload": st.presence[user]}, exclude=ws)
            elif t == "lock":
                kiln_id = payload.get("kiln_id", "")
                async with st.lock:
                    holder = st.locks.get(kiln_id)
                    if holder in (None, user):
                        st.locks[kiln_id] = user
                        granted = True
                    else:
                        granted = False
                if granted:
                    await ws.send_text(json.dumps({"t": "lock_granted", "room": room, "from": "server", "ts": _now(), "payload": {"kiln_id": kiln_id}}))
                    await _broadcast(room, {"t": "lock", "room": room, "from": "server", "ts": _now(), "payload": {"kiln_id": kiln_id, "holder": user}})
                else:
                    await ws.send_text(json.dumps({"t": "lock_denied", "room": room, "from": "server", "ts": _now(), "payload": {"kiln_id": kiln_id, "holder": holder}}))
            elif t == "unlock":
                kiln_id = payload.get("kiln_id", "")
                async with st.lock:
                    if st.locks.get(kiln_id) == user:
                        st.locks.pop(kiln_id, None)
                        holder = None
                    else:
                        holder = st.locks.get(kiln_id)
                await _broadcast(room, {"t": "lock", "room": room, "from": "server", "ts": _now(), "payload": {"kiln_id": kiln_id, "holder": holder}})
            elif t == "comment":
                c = {"id": payload.get("id") or str(uuid.uuid4()), "from": user,
                     "kiln_id": payload.get("kiln_id_or_null") or payload.get("kiln_id"),
                     "at": payload.get("at"), "body": payload.get("body", "")[:2000],
                     "ts": _now()}
                async with st.lock:
                    st.comments.append(c)
                await _broadcast(room, {"t": "comment", "room": room, "from": user, "ts": _now(), "payload": c})
            elif t == "snapshot_request":
                async with st.lock:
                    snap = st.snapshot
                    seq = st.seq
                if snap is None:
                    snap = store.load_snapshot(room)
                await ws.send_text(json.dumps({"t": "snapshot", "room": room, "from": "server", "ts": _now(), "payload": snap or {"seq": seq, "scene": {"objects": []}}}))
            elif t == "snapshot_push":
                scene = payload.get("scene", {})
                async with st.lock:
                    st.seq += 1
                    snap = {"seq": st.seq, "scene": scene, "server_ts": _now()}
                    st.snapshot = snap
                store.save_snapshot(room, snap)
                await _broadcast(room, {"t": "snapshot", "room": room, "from": user, "ts": _now(), "payload": snap})
            elif t == "bye":
                break
            else:
                await ws.send_text(json.dumps(err_frame(room, "unknown_kind", f"unknown t={t}")))
    except WebSocketDisconnect:
        log.info("leave room=%s user=%s (disconnect)", room, user)
    except Exception as e:
        log.warning("ws error room=%s user=%s: %s", room, user, e)
    finally:
        st.connections.discard(ws)
        # release locks held by user + notify
        released = []
        async with st.lock:
            for k, holder in list(st.locks.items()):
                if holder == user:
                    st.locks.pop(k, None)
                    released.append(k)
            st.presence.pop(user, None)
        for k in released:
            await _broadcast(room, {"t": "lock", "room": room, "from": "server", "ts": _now(), "payload": {"kiln_id": k, "holder": None}})


def cli():
    p = argparse.ArgumentParser(prog="kiln-server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args()
    import uvicorn
    uvicorn.run(app, host=a.host, port=a.port)


__all__ = ["app", "manager", "VERSION"]
