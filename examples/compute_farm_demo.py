# SPDX-License-Identifier: Apache-2.0
# Copyright (C) Kiln Contributors — see LICENSE-SERVER
"""Live farm demo: 2 fake workers + 1 frame job, all same-session. No Blender needed.

Usage: kiln-server running, then python examples/compute_farm_demo.py --server ws://127.0.0.1:8000 --room demo
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon"))
from kiln.net_ws import KilnWS


def ws_url(server: str, room: str, user: str) -> str:
    return f"{server.rstrip('/')}/v1/rooms/{urllib.parse.quote(room)}/ws?user={user}&client=0.1.0"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--server", default="ws://127.0.0.1:8000")
    p.add_argument("--room", default="demo")
    a = p.parse_args()

    ma, mb = [], []
    wa = KilnWS(ws_url(a.server, a.room, "farmer-a"), on_frame=ma.append)
    wb = KilnWS(ws_url(a.server, a.room, "farmer-b"), on_frame=mb.append)
    try:
        wa.connect(); wb.connect()
    except Exception as e:
        print(f"connect failed: {e} — start kiln-server first");
        return 1
    for w, u in ((wa, "farmer-a"), (wb, "farmer-b")):
        w.send({"t": "hello", "room": a.room, "from": u, "payload": {}})
    time.sleep(1.0)
    wa.send({"t": "worker.hello", "room": a.room, "from": "farmer-a",
             "payload": {"caps": {"cpu": 4, "blender": "4.2", "share": True}}})
    wb.send({"t": "worker.hello", "room": a.room, "from": "farmer-b",
             "payload": {"caps": {"cpu": 16, "gpu": "RTX", "blender": "4.2", "share": True}}})
    time.sleep(1.0)
    wa.send({"t": "job.submit", "room": a.room, "from": "farmer-a",
             "payload": {"type": "frame", "params": {"frame_start": 1, "frame_end": 3}}})
    time.sleep(1.0)
    posted = [m for m in ma + mb if m.get("t") == "job.posted"]
    if not posted:
        print("no job.posted — server didn't schedule");
        return 1
    jid = posted[0]["payload"]["job_id"]
    print(f"job {jid} posted, {posted[0]['payload']['total']} tasks. farmer-b claims…")
    wb.send({"t": "job.claim", "room": a.room, "from": "farmer-b", "payload": {"job_id": jid}})
    time.sleep(1.0)
    tasks = [m for m in mb if m.get("t") == "job.task"]
    if not tasks:
        print("no task granted");
        return 1
    tid = tasks[0]["payload"]["task_id"]
    print(f"claimed {tid}, reporting progress + result…")
    wb.send({"t": "job.progress", "room": a.room, "from": "farmer-b",
             "payload": {"job_id": jid, "task_id": tid, "pct": 50}})
    time.sleep(0.5)
    wb.send({"t": "job.result", "room": a.room, "from": "farmer-b",
             "payload": {"job_id": jid, "task_id": tid, "ok": True, "artifact": {"checksum": "demo"}}})
    time.sleep(1.0)
    base = a.server.replace("ws://", "http://").replace("wss://", "https://")
    with urllib.request.urlopen(f"{base}/v1/rooms/{a.room}/jobs/{jid}", timeout=6) as r:
        job = json.loads(r.read())
    print(f"server: {job['done']}/{job['total']} done, status={job['status']}")
    wa.close(); wb.close()
    print("OK — same-session farm works. Open 2 Blenders, Sharing ON, Submit Frames to see it live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
