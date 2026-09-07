"""Headless debug probe: healthz → debug/rooms → WS hello/op/presence. No Blender needed.

Usage: python examples/debug_probe.py [--server ws://127.0.0.1:8000] [--room demo]
Exit 0 = healthy, 1 = problem (message explains + fix).
"""
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon"))

from kiln.diagn import probe_server
from kiln.net_ws import KilnWS


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--server", default="ws://127.0.0.1:8000")
    p.add_argument("--room", default="demo")
    a = p.parse_args()

    rep = probe_server(a.server)
    print(f"[1/3] HTTP: {rep['message']}")
    if not rep.get("ok"):
        print(f"      FIX: {rep.get('fix')}")
        return 1
    if rep.get("fix"):
        print(f"      NEXT: {rep['fix']}")
    print(f"      NEXT: {rep.get('next')}")

    # WS round-trip via stdlib client
    import urllib.parse
    base = a.server.rstrip("/")
    url = f"{base}/v1/rooms/{urllib.parse.quote(a.room)}/ws?user=probe&client=0.1.0"
    msgs: list[dict] = []
    ws = KilnWS(url, on_frame=msgs.append)
    try:
        ws.connect(timeout=8)
    except Exception as e:
        print(f"[2/3] WS connect FAILED: {e}")
        print("      FIX: same host/port as HTTP, check firewall, server logs for 'join'.")
        return 1
    ws.send({"t": "hello", "room": a.room, "from": "probe", "payload": {"client": "0.1.0", "last_seq": 0}})
    time.sleep(1.2)
    ws.send({"t": "op", "room": a.room, "from": "probe",
             "payload": {"op_id": "probe-1", "kind": "transform", "kiln_id": "k-probe",
                         "base_seq": 0, "data": {"loc": [0, 0, 0], "name": "Probe"}}})
    ws.send({"t": "presence", "room": a.room, "from": "probe", "payload": {"selected": []}})
    time.sleep(1.2)
    kinds = [m.get("t") for m in msgs]
    print(f"[2/3] WS: got {len(msgs)} frames {kinds}")
    ws.close()
    if "welcome" not in kinds or "op" not in kinds:
        print("      FIX: server accepted TCP but didn't speak Kiln — version mismatch? Check server log.")
        return 1

    # room debug tail
    from kiln.diagn import http_base_from_ws
    base_http = http_base_from_ws(a.server)
    try:
        with urllib.request.urlopen(f"{base_http}/v1/rooms/{a.room}/debug", timeout=6) as r:
            dbg = json.loads(r.read())
        print(f"[3/3] room debug: seq={dbg['seq']} conns={dbg['connections']} users={[u['name'] for u in dbg['users']]} recent={len(dbg['recent_ops'])}")
    except Exception as e:
        print(f"[3/3] room debug FAILED: {e} (non-fatal)")
    print("OK — path is healthy. If Blender still fails, Export Log from its Kiln panel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
