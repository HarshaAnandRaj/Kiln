"""Kiln protocol models (Pydantic v2). Mirrors protocol/SPEC-v0.1.md."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field

FrameType = Literal[
    "hello", "welcome", "op", "presence", "lock", "unlock",
    "lock_granted", "lock_denied", "comment", "snapshot_push",
    "snapshot", "snapshot_request", "error", "bye",
]

OP_KINDS = {
    "object.upsert", "object.remove", "transform",
    "mesh.replace", "material.assign", "collection.link",
}

MAX_MESH_VERTS = 50_000


class OpPayload(BaseModel):
    op_id: str = Field(min_length=1, max_length=128)
    kind: str
    kiln_id: str = Field(min_length=1, max_length=128)
    base_seq: int = Field(default=0, ge=0)
    data: dict[str, Any] = Field(default_factory=dict)


class Frame(BaseModel):
    t: FrameType
    room: str = Field(min_length=1, max_length=64)
    model_config = {"extra": "allow"}
    from_: str = Field(alias="from", min_length=1, max_length=32)
    ts: float = 0.0
    seq: int | None = None
    server_ts: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


def validate_op_payload(p: dict) -> tuple[bool, str]:
    try:
        op = OpPayload(**p)
    except Exception as e:
        return False, f"bad_op_payload: {e}"
    if op.kind not in OP_KINDS:
        return False, f"unknown_kind: {op.kind}"
    if op.kind == "mesh.replace":
        verts = (op.data or {}).get("verts", [])
        if isinstance(verts, list) and len(verts) > MAX_MESH_VERTS:
            return False, "mesh_too_large"
    return True, ""
