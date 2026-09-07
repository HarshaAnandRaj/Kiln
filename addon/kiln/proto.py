# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) Kiln Contributors — see LICENSE-ADDON
"""Message builders/validators shared with server (no bpy, no deps)."""
from __future__ import annotations
import time
import uuid

ADDON_VERSION = "0.1.0"

OP_KINDS = (
    "object.upsert", "object.remove", "transform",
    "mesh.replace", "material.assign", "collection.link",
)

MAX_MESH_VERTS = 50_000


def now() -> float:
    return time.time()


def new_op_id() -> str:
    return str(uuid.uuid4())


def make_hello(room: str, user: str, last_seq: int = 0, color: str = "#e04f5e") -> dict:
    return {"t": "hello", "room": room, "from": user, "ts": now(),
            "payload": {"client": ADDON_VERSION, "last_seq": last_seq, "color": color}}


def make_op(room: str, user: str, kind: str, kiln_id: str, data: dict,
            base_seq: int = 0, op_id: str | None = None) -> dict:
    assert kind in OP_KINDS, f"unknown kind {kind}"
    if kind == "mesh.replace":
        verts = data.get("verts", [])
        if len(verts) > MAX_MESH_VERTS:
            raise ValueError("mesh_too_large")
    return {"t": "op", "room": room, "from": user, "ts": now(),
            "payload": {"op_id": op_id or new_op_id(), "kind": kind,
                        "kiln_id": kiln_id, "base_seq": base_seq, "data": data}}


def make_presence(room: str, user: str, selected: list[str] | None = None,
                  cursor: list[float] | None = None, mode: str = "OBJECT") -> dict:
    return {"t": "presence", "room": room, "from": user, "ts": now(),
            "payload": {"selected": selected or [], "cursor": cursor, "mode": mode}}


def make_lock(room: str, user: str, kiln_id: str) -> dict:
    return {"t": "lock", "room": room, "from": user, "ts": now(),
            "payload": {"kiln_id": kiln_id, "want": True}}


def fingerprint_transform(loc, rot, scale, name: str, visible: bool) -> tuple:
    """Hashable fingerprint for change detection (rounded to 1e-4)."""
    def r(v):
        return tuple(round(float(x), 4) for x in v)
    return (r(loc), r(rot), r(scale), name, bool(visible))
