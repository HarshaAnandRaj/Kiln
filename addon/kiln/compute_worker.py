# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) Kiln Contributors — see LICENSE-ADDON
"""Shared Compute worker (addon side). Pure helpers + bpy capability probe."""
from __future__ import annotations
import hashlib
import json
import os
import time


def detect_caps() -> dict:
    cpu = os.cpu_count() or 4
    mem_gb = 8.0
    try:  # psutil optional; never fail
        import psutil  # type: ignore
        mem_gb = round(psutil.virtual_memory().total / 1e9, 1)
    except Exception:
        pass
    gpu = None
    blender = "4.2"
    try:
        import bpy  # type: ignore
        blender = getattr(bpy.app, "version_string", "4.2")
        try:
            prefs = bpy.context.preferences.addons.get("cycles")
            if prefs:
                cp = prefs.preferences
                devs = getattr(cp, "devices", [])
                for d in devs:
                    if getattr(d, "use", False):
                        gpu = getattr(d, "name", "GPU") or "GPU"
                        break
        except Exception:
            pass
    except ImportError:
        pass
    return {"cpu": cpu, "mem_gb": mem_gb, "gpu": gpu, "blender": blender}


def hello_frame(room: str, user: str, share: bool, rtt_ms: int = 50, load: float = 0.0) -> dict:
    caps = detect_caps()
    caps.update({"share": share, "rtt_ms": rtt_ms, "load": load})
    return {"t": "worker.hello", "room": room, "from": user, "ts": time.time(),
            "payload": {"caps": caps}}


def submit_frame(room: str, user: str, fs: int, fe: int, samples: int = 32,
                 engine: str = "CYCLES", blend_version: str = "4.2") -> dict:
    return {"t": "job.submit", "room": room, "from": user, "ts": time.time(),
            "payload": {"type": "frame", "params": {"frame_start": fs, "frame_end": fe,
                                                   "samples": samples, "engine": engine,
                                                   "blend_version": blend_version}}}


def submit_tiles(room: str, user: str, frame: int = 1, grid: int = 2) -> dict:
    return {"t": "job.submit", "room": room, "from": user, "ts": time.time(),
            "payload": {"type": "tile", "params": {"frame": frame, "grid": grid, "blend_version": "4.2"}}}


def submit_bake(room: str, user: str, kind: str = "physics") -> dict:
    return {"t": "job.submit", "room": room, "from": user, "ts": time.time(),
            "payload": {"type": "bake", "params": {"kind": kind, "blend_version": "4.2"}}}


def fake_artifact(job_type: str, spec: dict) -> dict:
    """Deterministic stand-in for pixels/bake (v0.2). Real render plugs in here."""
    h = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]
    return {"checksum": h, "simulated": True, "note": "v0.2 sim — real pixels in v0.3 blob store"}
