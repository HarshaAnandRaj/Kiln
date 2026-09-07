# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) Kiln Contributors -- see LICENSE-ADDON
"""Stable Kiln IDs — bpy-independent core (testable without Blender)."""
from __future__ import annotations
import uuid

KILN_ID_KEY = "kiln_id"


def new_kiln_id() -> str:
    return str(uuid.uuid4())


def ensure_id(props: dict) -> tuple[str, bool]:
    """Ensure a dict-like custom-props object has a kiln_id. Returns (id, created)."""
    kid = props.get(KILN_ID_KEY)
    if isinstance(kid, str) and kid:
        return kid, False
    kid = new_kiln_id()
    try:
        props[KILN_ID_KEY] = kid
    except Exception:
        pass
    return kid, True


def get_id(props: dict) -> str | None:
    kid = props.get(KILN_ID_KEY)
    return kid if isinstance(kid, str) and kid else None
