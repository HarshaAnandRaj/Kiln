# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) Kiln Contributors � see LICENSE-ADDON
"""Kiln — Collaborative Editing for Blender (GPL-3.0-or-later).

Install: zip this folder as kiln.zip → Preferences → Add-ons → Install from Disk.
Requires Blender 4.2+ and a running kiln-server (ws://host:8000).
"""
bl_info = {
    "name": "Kiln Collaborative Editing",
    "author": "Kiln Contributors",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Kiln",
    "description": "Live collaborative editing: rooms, presence, locks, comments, snapshots",
    "category": "3D View",
}

import importlib

_submods = ["core_ids", "proto", "net_ws", "mesh_sync", "sync", "ui"]


def _reload():
    import sys
    pkg = __name__
    for m in _submods:
        full = f"{pkg}.{m}"
        if full in sys.modules:
            importlib.reload(sys.modules[full])


def register():
    _reload()
    from . import ui
    ui.register_ui()


def unregister():
    from . import ui
    ui.unregister_ui()


if __name__ != "__main__":
    pass
