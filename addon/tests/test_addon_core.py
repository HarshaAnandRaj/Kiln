# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) Kiln Contributors -- see LICENSE-ADDON
"""Addon core tests — no Blender needed (bpy imports are lazy/guarded)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kiln.core_ids import ensure_id, get_id
from kiln.proto import make_op, fingerprint_transform, make_hello
from kiln.mesh_sync import pack_mesh, unpack_mesh, mesh_fingerprint
from kiln.sync import SyncEngine, ObjSnap


def test_ids_stable():
    d: dict = {}
    kid, created = ensure_id(d)
    assert created and kid
    kid2, created2 = ensure_id(d)
    assert kid2 == kid and not created2
    assert get_id(d) == kid


def test_proto_op_and_cap():
    op = make_op("demo", "a", "transform", "k1", {"loc": [0, 0, 0]})
    assert op["payload"]["kind"] == "transform"
    hello = make_hello("demo", "a")
    assert hello["t"] == "hello"
    try:
        make_op("demo", "a", "mesh.replace", "k", {"verts": [[0, 0, 0]] * 50001})
    except ValueError as e:
        assert "mesh_too_large" in str(e)
    else:
        raise AssertionError("should cap")


def test_mesh_roundtrip():
    verts = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
    faces = [[0, 1, 2]]
    d = pack_mesh(verts, faces)
    v2, f2 = unpack_mesh(d)
    assert len(v2) == 3 and f2 == faces
    assert mesh_fingerprint(verts) != mesh_fingerprint([[9, 9, 9]] * 3)


def test_sync_diff_and_echo():
    e = SyncEngine()
    s1 = ObjSnap("k1", "Cube", "MESH", (0, 0, 0), (0, 0, 0), "XYZ", None, (1, 1, 1), True, None)
    e.commit({"k1": s1})
    up, rm = e.diff({"k1": s1})
    assert up == [] and rm == []
    s2 = ObjSnap("k1", "Cube", "MESH", (1, 0, 0), (0, 0, 0), "XYZ", None, (1, 1, 1), True, None)
    up, _ = e.diff({"k1": s2})
    assert len(up) == 1
    e.mark_sent("op-9")
    assert e.is_echo("op-9") and not e.is_echo("other")
    _, rm = e.diff({})
    assert rm == ["k1"]
