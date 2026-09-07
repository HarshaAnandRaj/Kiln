# SPDX-License-Identifier: Apache-2.0
# Copyright (C) Kiln Contributors -- see LICENSE-SERVER
"""Debug-endpoint + hint tests."""
import json
from fastapi.testclient import TestClient
from kiln_server.main import app

client = TestClient(app)


def test_debug_rooms_lists_room():
    room = "dbgroom1"
    with client.websocket_connect(f"/v1/rooms/{room}/ws?user=z") as ws:
        ws.send_text(json.dumps({"t": "hello", "room": room, "from": "z", "payload": {}}))
        json.loads(ws.receive_text())
        r = client.get("/v1/debug/rooms")
        assert r.status_code == 200
        rooms = {x["room"]: x for x in r.json()["rooms"]}
        assert room in rooms


def test_debug_room_tail_and_hints():
    room = "dbgroom2"
    with client.websocket_connect(f"/v1/rooms/{room}/ws?user=z") as ws:
        ws.send_text(json.dumps({"t": "hello", "room": room, "from": "z", "payload": {}}))
        json.loads(ws.receive_text())
        ws.send_text(json.dumps({"t": "op", "room": room, "from": "z",
                                 "payload": {"op_id": "d1", "kind": "transform",
                                             "kiln_id": "k", "data": {}}}))
        json.loads(ws.receive_text())
        r = client.get(f"/v1/rooms/{room}/debug")
        body = r.json()
        assert body["seq"] >= 1
        assert body["recent_ops"][-1]["kind"] == "transform"
        assert "hints" in body


def test_error_frames_carry_hints():
    room = "dbgroom3"
    with client.websocket_connect(f"/v1/rooms/{room}/ws?user=z") as ws:
        ws.send_text(json.dumps({"t": "hello", "room": room, "from": "z", "payload": {}}))
        json.loads(ws.receive_text())
        ws.send_text(json.dumps({"t": "frobnicate", "room": room, "from": "z", "payload": {}}))
        err = json.loads(ws.receive_text())
        assert err["t"] == "error"
        assert "fix" in err["payload"] and err["payload"]["fix"]
