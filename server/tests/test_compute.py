# SPDX-License-Identifier: Apache-2.0
# Copyright (C) Kiln Contributors — see LICENSE-SERVER
"""Compute scheduler + job API tests (same-session farm)."""
import json
from fastapi.testclient import TestClient
from kiln_server.main import app
from kiln_server import compute as C

client = TestClient(app)


def test_expand_frame_tile_bake():
    jf = C.expand_job("r", "a", "frame", {"frame_start": 1, "frame_end": 4})
    assert len(jf.tasks) == 4 and jf.tasks[0].spec["frame"] == 1
    jt = C.expand_job("r", "a", "tile", {"grid": 2, "frame": 7})
    assert len(jt.tasks) == 4 and jt.tasks[0].spec["grid"] == 2
    jb = C.expand_job("r", "a", "bake", {"kind": "physics"})
    assert len(jb.tasks) == 1


def test_smart_allocation_prefers_beefy():
    job = C.expand_job("r", "a", "frame", {"frame_start": 1, "frame_end": 1, "blend_version": "4.2"})
    weak = C.WorkerCaps("weak", cpu=2, mem_gb=4, blender="4.2", share=True, load=0.0, rtt_ms=50)
    strong = C.WorkerCaps("strong", cpu=16, mem_gb=32, gpu="RTX", blender="4.2", share=True, load=0.0, rtt_ms=20)
    assert C.score_worker(strong, job) > C.score_worker(weak, job)
    assert C.best_worker([weak, strong], job).user == "strong"
    off = C.WorkerCaps("off", cpu=64, share=False)
    assert C.best_worker([off, weak], job).user == "weak"


def test_job_flow_ws_two_workers():
    room = "computeroom1"
    with client.websocket_connect(f"/v1/rooms/{room}/ws?user=alice") as a:
        a.send_text(json.dumps({"t": "hello", "room": room, "from": "alice", "payload": {}}))
        json.loads(a.receive_text())
        with client.websocket_connect(f"/v1/rooms/{room}/ws?user=bob") as b:
            b.send_text(json.dumps({"t": "hello", "room": room, "from": "bob", "payload": {}}))
            json.loads(b.receive_text())
            # both advertise
            a.send_text(json.dumps({"t": "worker.hello", "room": room, "from": "alice",
                                    "payload": {"caps": {"cpu": 4, "blender": "4.2", "share": True}}}))
            wlist = json.loads(a.receive_text())  # worker.list to alice
            assert wlist["t"] == "worker.list"
            json.loads(b.receive_text())  # worker.list to bob
            # alice submits frame job 1-2
            a.send_text(json.dumps({"t": "job.submit", "room": room, "from": "alice",
                                    "payload": {"type": "frame", "params": {"frame_start": 1, "frame_end": 2}}}))
            posted_a = json.loads(a.receive_text())
            posted_b = json.loads(b.receive_text())
            assert posted_a["t"] == "job.posted" and posted_a["payload"]["total"] == 2
            jid = posted_a["payload"]["job_id"]
            # bob claims
            b.send_text(json.dumps({"t": "job.claim", "room": room, "from": "bob",
                                    "payload": {"job_id": jid}}))
            task = json.loads(b.receive_text())
            assert task["t"] == "job.task"
            # bob completes
            b.send_text(json.dumps({"t": "job.result", "room": room, "from": "bob",
                                    "payload": {"job_id": jid, "task_id": task["payload"]["task_id"],
                                                "ok": True, "artifact": {"checksum": "abc"}}}))
            res_b = json.loads(b.receive_text())
            assert res_b["t"] == "job.result"
            res_a = json.loads(a.receive_text())
            assert res_a["t"] in ("job.progress", "job.result")


def test_bake_goes_to_best_worker():
    room = "computeroom2"
    with client.websocket_connect(f"/v1/rooms/{room}/ws?user=weak") as w:
        w.send_text(json.dumps({"t": "hello", "room": room, "from": "weak", "payload": {}}))
        json.loads(w.receive_text())
        with client.websocket_connect(f"/v1/rooms/{room}/ws?user=strong") as s:
            s.send_text(json.dumps({"t": "hello", "room": room, "from": "strong", "payload": {}}))
            json.loads(s.receive_text())
            w.send_text(json.dumps({"t": "worker.hello", "room": room, "from": "weak",
                                    "payload": {"caps": {"cpu": 2, "blender": "4.2", "share": True}}}))
            json.loads(w.receive_text()); json.loads(s.receive_text())
            s.send_text(json.dumps({"t": "worker.hello", "room": room, "from": "strong",
                                    "payload": {"caps": {"cpu": 32, "gpu": "RTX", "blender": "4.2", "share": True}}}))
            json.loads(w.receive_text()); json.loads(s.receive_text())
            w.send_text(json.dumps({"t": "job.submit", "room": room, "from": "weak",
                                    "payload": {"type": "bake", "params": {}}}))
            posted_w = json.loads(w.receive_text()); posted_s = json.loads(s.receive_text())
            jid = posted_w["payload"]["job_id"]
            w.send_text(json.dumps({"t": "job.claim", "room": room, "from": "weak", "payload": {"job_id": jid}}))
            assert json.loads(w.receive_text())["t"] == "job.wait"  # weak denied
            s.send_text(json.dumps({"t": "job.claim", "room": room, "from": "strong", "payload": {"job_id": jid}}))
            assert json.loads(s.receive_text())["t"] == "job.task"
