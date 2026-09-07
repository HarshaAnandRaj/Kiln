"""diagn tests — headless (no Blender)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kiln.diagn import RingLog, hint_for, probe_server, http_base_from_ws


def test_ringlog_bounded():
    rl = RingLog(3)
    for i in range(5):
        rl.add("INFO", f"m{i}")
    assert len(rl.last(10)) == 3
    assert "m4" in rl.dump()


def test_hints_human():
    assert "50k" in hint_for("mesh_too_large")
    assert hint_for("nope")  # fallback always non-empty


def test_http_base():
    assert http_base_from_ws("ws://127.0.0.1:8000") == "http://127.0.0.1:8000"
    assert http_base_from_ws("wss://x:443") == "https://x:443"


def test_probe_unreachable_is_friendly():
    rep = probe_server("ws://127.0.0.1:59999", timeout=1.0)
    assert rep["ok"] is False
    assert "fix" in rep and rep["fix"]
