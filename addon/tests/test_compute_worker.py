# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) Kiln Contributors — see LICENSE-ADDON
"""compute_worker tests — headless."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kiln.compute_worker import detect_caps, hello_frame, submit_frame, fake_artifact


def test_caps_sane():
    c = detect_caps()
    assert c["cpu"] >= 1 and "blender" in c


def test_frames_build():
    m = hello_frame("demo", "a", True)
    assert m["t"] == "worker.hello" and m["payload"]["caps"]["share"] is True
    j = submit_frame("demo", "a", 1, 3)
    assert j["payload"]["params"]["frame_end"] == 3
    art = fake_artifact("frame", {"frame": 1})
    assert art["checksum"] and art["simulated"] is True
