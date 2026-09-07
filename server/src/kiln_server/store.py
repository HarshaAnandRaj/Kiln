# SPDX-License-Identifier: Apache-2.0
# Copyright (C) Kiln Contributors — see LICENSE-SERVER
"""JSONL + snapshot persistence (crash-safe, stdlib only)."""
from __future__ import annotations
import json
import os
from pathlib import Path


def data_dir() -> Path:
    d = Path(os.environ.get("KILN_DATA", "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def append_op(room: str, frame: dict) -> None:
    try:
        with open(data_dir() / f"{room}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(frame) + "\n")
    except OSError:
        pass


def save_snapshot(room: str, snapshot: dict) -> None:
    try:
        tmp = data_dir() / f"{room}.snapshot.tmp"
        dst = data_dir() / f"{room}.snapshot.json"
        tmp.write_text(json.dumps(snapshot), encoding="utf-8")
        tmp.replace(dst)
    except OSError:
        pass


def load_snapshot(room: str) -> dict | None:
    try:
        p = data_dir() / f"{room}.snapshot.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return None
