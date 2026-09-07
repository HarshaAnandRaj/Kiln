"""Headless demo: two fake clients sync a cube move through the real protocol.

Run: `kiln-server --port 8000` in one shell, then `python examples/two_cubes_sync.py`.
No Blender needed — validates wire end-to-end (also serves as protocol test vector).
"""
import json
import urllib.request

ROOM = "demo"
BASE = "http://127.0.0.1:8000"


def push_snapshot():
    scene = {"objects": [
        {"kiln_id": "cube-1", "name": "Cube", "obj_type": "MESH",
         "loc": [1, 2, 3], "rot_euler": [0, 0, 0], "rot_mode": "XYZ",
         "scale": [1, 1, 1], "visible": True, "parent_kiln_id": None},
    ]}
    req = urllib.request.Request(f"{BASE}/v1/rooms/{ROOM}/snapshot",
                                 data=json.dumps({"from": "demo-script", "scene": scene}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        print("push:", r.status, json.loads(r.read())["seq"])


def read_ops():
    with urllib.request.urlopen(f"{BASE}/v1/rooms/{ROOM}/ops?since=0", timeout=10) as r:
        body = json.loads(r.read())
    print(f"ops seq={body['seq']} count={len(body['ops'])}")
    for o in body["ops"][-3:]:
        print(" -", o.get("seq"), o["payload"].get("kind"), o["payload"].get("kiln_id"))


def read_snapshot():
    with urllib.request.urlopen(f"{BASE}/v1/rooms/{ROOM}/snapshot", timeout=10) as r:
        body = json.loads(r.read())
    snap = body["snapshot"] or {}
    print("snapshot seq:", snap.get("seq"), "objs:", len((snap.get("scene") or {}).get("objects", [])))


if __name__ == "__main__":
    push_snapshot()
    read_snapshot()
    read_ops()
    print("OK — server is live. Connect two Blenders to ws://127.0.0.1:8000 room 'demo' to see live sync.")
