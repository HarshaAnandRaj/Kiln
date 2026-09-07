# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) Kiln Contributors -- see LICENSE-ADDON
"""Mesh pack/unpack — pure functions (no bpy) + thin bpy adapters."""
from __future__ import annotations

MAX_VERTS = 50_000


def pack_mesh(verts: list, faces: list[list[int]]) -> dict:
    """verts: iterable of (x,y,z), faces: list of index lists. Returns JSON-able dict."""
    v = [[float(c) for c in co] for co in verts]
    if len(v) > MAX_VERTS:
        raise ValueError("mesh_too_large")
    polys = [[int(i) for i in f] for f in faces]
    return {"verts": v, "polys": polys}


def unpack_mesh(data: dict) -> tuple[list, list]:
    verts = [[float(x) for x in co] for co in data.get("verts", [])]
    polys = [[int(i) for i in f] for f in data.get("polys", [])]
    return verts, polys


def mesh_fingerprint(verts: list) -> tuple:
    n = len(verts)
    if n == 0:
        return (0,)
    # cheap: count + sum + first/last (rounded) — enough to detect edits
    sx = sum(c[0] for c in verts)
    sy = sum(c[1] for c in verts)
    sz = sum(c[2] for c in verts)
    f = verts[0]
    l = verts[-1]
    return (n, round(sx, 3), round(sy, 3), round(sz, 3),
            tuple(round(float(x), 4) for x in f), tuple(round(float(x), 4) for x in l))


# -- bpy adapters (import bpy lazily so tests run without Blender) --
def pack_bpy_mesh(obj) -> dict | None:
    try:
        import bpy  # noqa
    except ImportError:
        return None
    if getattr(obj, "type", "") != "MESH" or getattr(obj, "data", None) is None:
        return None
    me = obj.data
    try:
        verts = [tuple(v.co) for v in me.vertices]
        faces = [list(p.vertices) for p in me.polygons]
    except Exception:
        return None
    if len(verts) > MAX_VERTS:
        return None
    return pack_mesh(verts, faces)


def apply_bpy_mesh(obj, data: dict) -> bool:
    try:
        import bpy  # noqa
    except ImportError:
        return False
    try:
        verts, polys = unpack_mesh(data)
        me = obj.data
        me.clear_geometry()
        me.from_pydata(verts, [], polys)
        me.update()
        return True
    except Exception:
        return False
