# SPDX-License-Identifier: Apache-2.0
# Copyright (C) Kiln Contributors -- see LICENSE-SERVER
"""Protocol + room tests (no Blender needed)."""
import json
from fastapi.testclient import TestClient
from kiln_server.main import app

client = TestClient(app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_op_broadcast_and_replay():
    room = "testroom1"
    with client.websocket_connect(f"/v1/rooms/{room}/ws?user=alice") as ws:
        ws.send_text(json.dumps({"t": "hello", "room": room, "from": "alice",
                                 "payload": {"client": "0.1.0", "last_seq": 0}}))
        welcome = json.loads(ws.receive_text())
        assert welcome["t"] == "welcome"
        seq0 = welcome["payload"]["seq"]
        op = {"t": "op", "room": room, "from": "alice",
              "payload": {"op_id": "op-1", "kind": "transform",
                          "kiln_id": "k1", "base_seq": seq0,
                          "data": {"loc": [1, 2, 3], "name": "Cube"}}}
        ws.send_text(json.dumps(op))
        got = json.loads(ws.receive_text())
        assert got["t"] == "op"
        assert got["seq"] == seq0 + 1
        assert got["payload"]["op_id"] == "op-1"
    # replay via REST
    r = client.get(f"/v1/rooms/{room}/ops?since={seq0}")
    assert r.status_code == 200
    assert len(r.json()["ops"]) >= 1


def test_unknown_kind_rejected():
    room = "testroom2"
    with client.websocket_connect(f"/v1/rooms/{room}/ws?user=bob") as ws:
        ws.send_text(json.dumps({"t": "hello", "room": room, "from": "bob", "payload": {}}))
        json.loads(ws.receive_text())  # welcome
        ws.send_text(json.dumps({"t": "op", "room": room, "from": "bob",
                                 "payload": {"op_id": "x", "kind": "nope.zone",
                                             "kiln_id": "k", "data": {}}}))
        err = json.loads(ws.receive_text())
        assert err["t"] == "error"


def test_mesh_too_large_rejected():
    room = "testroom3"
    with client.websocket_connect(f"/v1/rooms/{room}/ws?user=carol") as ws:
        ws.send_text(json.dumps({"t": "hello", "room": room, "from": "carol", "payload": {}}))
        json.loads(ws.receive_text())
        ws.send_text(json.dumps({"t": "op", "room": room, "from": "carol",
                                 "payload": {"op_id": "m1", "kind": "mesh.replace",
                                             "kiln_id": "k", "data": {"verts": [[0, 0, 0]] * 50001}}}))
        err = json.loads(ws.receive_text())
        assert err["t"] == "error"
        assert err["payload"]["code"] == "mesh_too_large"


def test_lock_grant_and_deny():
    room = "testroom4"
    with client.websocket_connect(f"/v1/rooms/{room}/ws?user=u1") as a:
        a.send_text(json.dumps({"t": "hello", "room": room, "from": "u1", "payload": {}}))
        json.loads(a.receive_text())
        with client.websocket_connect(f"/v1/rooms/{room}/ws?user=u2") as b:
            b.send_text(json.dumps({"t": "hello", "room": room, "from": "u2", "payload": {}}))
            json.loads(b.receive_text())
            a.send_text(json.dumps({"t": "lock", "room": room, "from": "u1", "payload": {"kiln_id": "K"}}))
            assert json.loads(a.receive_text())["t"] == "lock_granted"
            # u1's broadcast also goes to b
            assert json.loads(b.receive_text())["payload"]["holder"] == "u1"
            b.send_text(json.dumps({"t": "lock", "room": room, "from": "u2", "payload": {"kiln_id": "K"}}))
            denied = json.loads(b.receive_text())
            assert denied["t"] == "lock_denied"
