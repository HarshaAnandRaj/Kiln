"""Kiln Blender UI + connection state. Loaded only inside Blender."""
from __future__ import annotations
import queue
import threading
import time
import urllib.parse
import urllib.request
import json

import bpy

from . import proto
from .core_ids import KILN_ID_KEY
from .net_ws import KilnWS
from .sync import SyncEngine, scan_bpy_scene, ensure_bpy_ids, apply_op_bpy, ObjSnap
from . import mesh_sync
from .diagn import RingLog, hint_for, probe_server


class KilnState:
    def __init__(self):
        self.ws: KilnWS | None = None
        self.engine = SyncEngine()
        self.connected = False
        self.connecting = False
        self.room = ""
        self.user = ""
        self.server_ws_base = ""
        self.server_http_base = ""
        self.last_seq = 0
        self.status = "Offline — press Connect"
        self.users: dict[str, str] = {}
        self.comments: list[dict] = []
        self.errors: list[str] = []
        self._presence_at = 0.0
        self._mesh_at: dict[str, float] = {}
        self._reconnect_at = 0.0
        self._inbox_drain = 0
        # debug / friendliness
        self.log = RingLog(500)
        self.sent_count = 0
        self.recv_count = 0
        self.rtt_ms = -1
        self.diag: dict = {}
        self._hello_at = 0.0

    def http_base(self) -> str:
        return self.server_http_base

STATE = KilnState()


def log(level: str, msg: str):
    try:
        STATE.log.add(level, msg)
    except Exception:
        pass
    if level == "ERROR":
        try:
            STATE.errors.append(msg)
            STATE.errors = STATE.errors[-20:]
        except Exception:
            pass


def _props():
    sc = bpy.context.scene
    return sc.kiln_server, sc.kiln_room, sc.kiln_user, sc.kiln_color


def _http_base(ws_base: str) -> str:
    # ws://host:port[/prefix] -> http://host:port[/prefix], strip trailing /v1 or /ws paths
    u = urllib.parse.urlparse(ws_base)
    scheme = "https" if u.scheme == "wss" else "http"
    return f"{scheme}://{u.hostname}:{u.port or (443 if scheme=='https' else 80)}"


def _ws_url(ws_base: str, room: str, user: str) -> str:
    base = ws_base.rstrip("/")
    if base.endswith("/ws"):
        base = base[: -len("/ws")]
    if "/v1/rooms" in base:
        base = base.split("/v1/rooms")[0]
    if not base.endswith("/v1"):
        # allow bare host -> assume /v1/rooms
        pass
    q = urllib.parse.urlencode({"user": user, "client": proto.ADDON_VERSION})
    return f"{base}/v1/rooms/{urllib.parse.quote(room)}/ws?{q}"


def connect_now():
    server, room, user, color = _props()
    server, room, user = server.strip(), room.strip() or "demo", user.strip() or "artist"
    if STATE.connected or STATE.connecting:
        return
    STATE.connecting = True
    STATE.status = f"Connecting to {room}…"
    STATE.room, STATE.user = room, user
    STATE.server_ws_base = server
    STATE.server_http_base = _http_base(server)

    def on_close(reason):
        STATE.connected = False
        STATE.connecting = False
        STATE.status = f"Disconnected ({reason}) — retry in 5s"
        STATE._reconnect_at = time.time() + 5.0

    url = _ws_url(server, room, user)
    # Friendly pre-flight: is the server even up? (fast HTTP check, no WS yet)
    try:
        from .diagn import probe_server as _probe
        rep = _probe(server, timeout=4.0)
        STATE.diag = rep
        if not rep.get("ok"):
            STATE.connecting = False
            STATE.status = "Server unreachable — see Troubleshooting"
            log("ERROR", f"preflight: {rep.get('message')} FIX: {rep.get('fix')}")
            return
        STATE.rtt_ms = rep.get("latency_ms", -1)
    except Exception as e:
        log("WARN", f"preflight skipped: {e}")
    ws = KilnWS(url, on_close=on_close)
    STATE.ws = ws
    log("INFO", f"connecting to {url} as {user} in '{room}'…")

    def _do():
        try:
            STATE._hello_at = time.time()
            ws.connect(timeout=10)
            ws.send(proto.make_hello(room, user, STATE.last_seq, color))
            STATE.connected = True
            STATE.connecting = False
            STATE.status = f"Live in '{room}' as {user}"
            log("INFO", f"connected (http rtt {STATE.rtt_ms}ms). Syncing…")
            ensure_bpy_ids()
            STATE.engine.commit(scan_bpy_scene())
        except Exception as e:
            STATE.connecting = False
            STATE.status = "Connect failed — see Troubleshooting"
            log("ERROR", f"connect failed: {e}. FIX: Server URL like ws://127.0.0.1:8000, same room both sides.")
            STATE._reconnect_at = time.time() + 5.0
    threading.Thread(target=_do, daemon=True, name="kiln-connect").start()


def disconnect_now():
    if STATE.ws:
        try:
            STATE.ws.send({"t": "bye", "room": STATE.room, "from": STATE.user, "payload": {}})
        except Exception:
            pass
        try:
            STATE.ws.close()
        except Exception:
            pass
    STATE.ws = None
    STATE.connected = False
    STATE.connecting = False
    STATE.status = "Offline"


def kiln_timer():
    """Main pump — runs on Blender main thread every 0.2s."""
    try:
        if not STATE.connected or STATE.ws is None:
            # auto-reconnect
            if STATE._reconnect_at and time.time() >= STATE._reconnect_at and not STATE.connecting:
                STATE._reconnect_at = 0.0
                connect_now()
            return 0.2
        # 1. drain inbox
        drained = 0
        while drained < 50:
            try:
                msg = STATE.ws.inbox.get_nowait()
            except queue.Empty:
                break
            drained += 1
            handle_frame(msg)
        # 2. local scan → ops (skip while applying remote)
        if not STATE.engine.suppress:
            try:
                current = scan_bpy_scene()
                upserts, removes = STATE.engine.diff(current)
                for snap in upserts[:20]:  # cap per tick
                    if snap.kiln_id in STATE.engine.locks and STATE.engine.locks[snap.kiln_id] not in (None, STATE.user):
                        continue  # respect soft lock
                    data = {"obj_type": snap.obj_type, "name": snap.name,
                            "loc": list(snap.loc), "rot_mode": snap.rot_mode,
                            "scale": list(snap.scale), "visible": snap.visible,
                            "parent_kiln_id": snap.parent_kiln_id}
                    if snap.rot_mode == "QUATERNION":
                        data["rot_quaternion"] = list(snap.rot)
                    else:
                        data["rot_euler"] = list(snap.rot)
                    kind = "object.upsert" if snap.kiln_id not in STATE.engine.snaps else "transform"
                    op = proto.make_op(STATE.room, STATE.user, kind, snap.kiln_id, data, STATE.last_seq)
                    STATE.engine.mark_sent(op["payload"]["op_id"])
                    try:
                        STATE.ws.send(op)
                        STATE.sent_count += 1
                    except Exception as e:
                        STATE.status = f"Send failed: {e}"
                        log("ERROR", f"send failed: {e}. FIX: Test Connection, then reconnect.")
                        break
                for kid in removes[:20]:
                    op = proto.make_op(STATE.room, STATE.user, "object.remove", kid, {}, STATE.last_seq)
                    STATE.engine.mark_sent(op["payload"]["op_id"])
                    try:
                        STATE.ws.send(op)
                        STATE.sent_count += 1
                    except Exception:
                        break
                STATE.engine.commit(current)
            except Exception as e:
                STATE.errors.append(f"scan: {e}")
        # 3. presence @ ~2Hz
        if time.time() - STATE._presence_at > 0.5:
            STATE._presence_at = time.time()
            try:
                sel = []
                for o in bpy.context.selected_objects:
                    kid = o.get(KILN_ID_KEY)
                    if isinstance(kid, str):
                        sel.append(kid)
                cursor = list(bpy.context.scene.cursor.location)
                STATE.ws.send(proto.make_presence(STATE.room, STATE.user, sel, cursor))
            except Exception:
                pass
    except Exception as e:
        STATE.errors.append(f"timer: {e}")
    return 0.2


def handle_frame(msg: dict):
    t = msg.get("t")
    payload = msg.get("payload") or {}
    STATE.recv_count += 1
    if "seq" in msg and isinstance(msg["seq"], int):
        STATE.last_seq = max(STATE.last_seq, msg["seq"])
    if t == "welcome":
        if STATE._hello_at:
            STATE.rtt_ms = int((time.time() - STATE._hello_at) * 1000)
        STATE.last_seq = max(STATE.last_seq, int(payload.get("seq", 0)))
        for u in payload.get("users", []):
            STATE.users[u.get("name", "?")] = u.get("color", "#888")
        for kid, holder in (payload.get("locks") or {}).items():
            if holder:
                STATE.engine.locks[kid] = holder
        STATE.status = f"Live in '{STATE.room}' as {STATE.user} (seq {STATE.last_seq})"
        log("INFO", f"welcome: seq={STATE.last_seq} rtt={STATE.rtt_ms}ms users={len(STATE.users)}")
        # catch up
        try:
            STATE.ws.send({"t": "snapshot_request", "room": STATE.room, "from": STATE.user, "payload": {}})
        except Exception:
            pass
    elif t == "op":
        op_id = payload.get("op_id", "")
        if STATE.engine.is_echo(op_id):
            return
        kiln_id = payload.get("kiln_id", "")
        STATE.engine.suppress = True
        try:
            res = apply_op_bpy(payload, kiln_id)
            STATE.engine.commit(scan_bpy_scene())
            log("DEBUG", f"op {payload.get('kind')} {kiln_id[:8]} from {msg.get('from')} -> {res}")
        finally:
            STATE.engine.suppress = False
    elif t == "presence":
        frm = msg.get("from", "?")
        STATE.users[frm] = (payload.get("color") or STATE.users.get(frm, "#888"))
        update_presence_empty(frm, payload)
    elif t == "lock":
        kid, holder = payload.get("kiln_id"), payload.get("holder")
        if holder:
            STATE.engine.locks[kid] = holder
            if holder != STATE.user:
                log("INFO", f"lock: {kid[:8]} held by {holder}")
        else:
            STATE.engine.locks.pop(kid, None)
    elif t in ("lock_granted", "lock_denied"):
        kid = payload.get("kiln_id")
        if t == "lock_granted":
            STATE.engine.locks[kid] = STATE.user
            STATE.status = f"Locked {kid[:8]}"
            log("INFO", f"you locked {kid[:8]}")
        else:
            STATE.status = f"Lock denied — held by {payload.get('holder')}"
            log("WARN", f"lock denied on {str(kid)[:8]} by {payload.get('holder')}. Pick another object.")
    elif t == "comment":
        STATE.comments.append(payload)
        STATE.comments = STATE.comments[-50:]
        log("INFO", f"comment from {payload.get('from')}: {(payload.get('body') or '')[:80]}")
    elif t == "snapshot":
        apply_snapshot(payload.get("scene") or {})
    elif t == "error":
        code = payload.get("code", "internal")
        hint = payload.get("fix") or hint_for(code)
        STATE.errors.append(f"{code}: {payload.get('detail')} — {hint}")
        STATE.errors = STATE.errors[-20:]
        STATE.status = f"Server: {code}"
        log("ERROR", f"{code}: {payload.get('detail')} FIX: {hint}")


def update_presence_empty(user: str, payload: dict):
    if user == STATE.user:
        return
    try:
        name = f"KILN_presence_{user}"
        obj = bpy.data.objects.get(name)
        if obj is None:
            obj = bpy.data.objects.new(name, None)
            obj.empty_display_type = "SPHERE"
            obj.empty_display_size = 0.15
            bpy.context.scene.collection.objects.link(obj)
        cur = payload.get("cursor")
        if cur and len(cur) == 3:
            obj.location = cur
    except Exception:
        pass


def apply_snapshot(scene: dict):
    STATE.engine.suppress = True
    try:
        ensure_bpy_ids()
        for o in scene.get("objects", []):
            kid = o.get("kiln_id")
            if not kid:
                continue
            apply_op_bpy({"kind": "object.upsert", "data": o}, kid)
            if o.get("mesh"):
                apply_op_bpy({"kind": "mesh.replace", "data": o["mesh"]}, kid)
        STATE.engine.commit(scan_bpy_scene())
        STATE.status = f"Snapshot applied ({len(scene.get('objects', []))} objs)"
    finally:
        STATE.engine.suppress = False


# ---------------- Operators ----------------
class KILN_OT_connect(bpy.types.Operator):
    bl_idname = "kiln.connect"
    bl_label = "Connect"
    def execute(self, context):
        connect_now()
        return {"FINISHED"}


class KILN_OT_disconnect(bpy.types.Operator):
    bl_idname = "kiln.disconnect"
    bl_label = "Disconnect"
    def execute(self, context):
        disconnect_now()
        return {"FINISHED"}


class KILN_OT_lock_selected(bpy.types.Operator):
    bl_idname = "kiln.lock_selected"
    bl_label = "Lock Selected"
    def execute(self, context):
        if not STATE.connected or not STATE.ws:
            self.report({"WARNING"}, "Not connected")
            return {"CANCELLED"}
        for o in context.selected_objects:
            kid = o.get(KILN_ID_KEY)
            if kid:
                STATE.ws.send(proto.make_lock(STATE.room, STATE.user, kid))
        return {"FINISHED"}


class KILN_OT_unlock_selected(bpy.types.Operator):
    bl_idname = "kiln.unlock_selected"
    bl_label = "Unlock Selected"
    def execute(self, context):
        if not STATE.connected or not STATE.ws:
            return {"CANCELLED"}
        for o in context.selected_objects:
            kid = o.get(KILN_ID_KEY)
            if kid:
                STATE.ws.send({"t": "unlock", "room": STATE.room, "from": STATE.user, "payload": {"kiln_id": kid}})
        return {"FINISHED"}


class KILN_OT_push_mesh(bpy.types.Operator):
    bl_idname = "kiln.push_mesh"
    bl_label = "Push Mesh Selected"
    bl_description = "Send full mesh of selected objects (capped 50k verts)"
    def execute(self, context):
        if not STATE.connected or not STATE.ws:
            self.report({"WARNING"}, "Not connected")
            return {"CANCELLED"}
        n = 0
        for o in context.selected_objects:
            if getattr(o, "type", "") != "MESH":
                continue
            kid = o.get(KILN_ID_KEY)
            if not kid:
                continue
            now = time.time()
            if now - STATE._mesh_at.get(kid, 0) < 0.5:
                continue
            STATE._mesh_at[kid] = now
            data = mesh_sync.pack_bpy_mesh(o)
            if data is None:
                self.report({"WARNING"}, f"{o.name}: mesh too large or unreadable")
                continue
            op = proto.make_op(STATE.room, STATE.user, "mesh.replace", kid, data, STATE.last_seq)
            STATE.engine.mark_sent(op["payload"]["op_id"])
            STATE.ws.send(op)
            n += 1
        self.report({"INFO"}, f"Pushed {n} mesh(es)")
        return {"FINISHED"}


class KILN_OT_push_snapshot(bpy.types.Operator):
    bl_idname = "kiln.push_snapshot"
    bl_label = "Push Snapshot"
    def execute(self, context):
        if not STATE.connected or not STATE.ws:
            self.report({"WARNING"}, "Not connected")
            return {"CANCELLED"}
        current = scan_bpy_scene()
        objs = []
        for kid, s in current.items():
            d = {"kiln_id": kid, "name": s.name, "obj_type": s.obj_type,
                 "loc": list(s.loc), "rot_mode": s.rot_mode, "scale": list(s.scale),
                 "visible": s.visible, "parent_kiln_id": s.parent_kiln_id}
            if s.rot_mode == "QUATERNION":
                d["rot_quaternion"] = list(s.rot)
            else:
                d["rot_euler"] = list(s.rot)
            objs.append(d)
        STATE.ws.send({"t": "snapshot_push", "room": STATE.room, "from": STATE.user,
                       "payload": {"scene": {"objects": objs}}})
        self.report({"INFO"}, f"Snapshot pushed ({len(objs)} objs)")
        return {"FINISHED"}


class KILN_OT_pull_snapshot(bpy.types.Operator):
    bl_idname = "kiln.pull_snapshot"
    bl_label = "Pull Snapshot"
    def execute(self, context):
        if not STATE.connected or not STATE.ws:
            return {"CANCELLED"}
        STATE.ws.send({"t": "snapshot_request", "room": STATE.room, "from": STATE.user, "payload": {}})
        return {"FINISHED"}


class KILN_OT_add_comment(bpy.types.Operator):
    bl_idname = "kiln.add_comment"
    bl_label = "Comment @ Cursor"
    bl_description = "Pin a note at the 3D cursor for the whole room"
    body: bpy.props.StringProperty(name="Comment", default="")
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    def execute(self, context):
        if not STATE.connected or not STATE.ws:
            self.report({"WARNING"}, "Not connected — press Connect first")
            return {"CANCELLED"}
        cur = list(context.scene.cursor.location)
        STATE.ws.send({"t": "comment", "room": STATE.room, "from": STATE.user,
                       "payload": {"at": cur, "body": self.body[:2000]}})
        self.report({"INFO"}, "Comment shared")
        return {"FINISHED"}


class KILN_OT_test_connection(bpy.types.Operator):
    bl_idname = "kiln.test_connection"
    bl_label = "Test Connection"
    bl_description = "Check server health + latency without joining (shows how to fix)"
    def execute(self, context):
        sc = context.scene
        rep = probe_server(sc.kiln_server, timeout=6.0)
        STATE.diag = rep
        if rep.get("ok"):
            STATE.status = f"Server OK ({rep['latency_ms']}ms) — press Connect"
            log("INFO", f"test: {rep['message']} {rep.get('next','')}")
            self.report({"INFO"}, rep["message"])
        else:
            STATE.status = "Server unreachable — see Troubleshooting"
            log("ERROR", f"test failed at {rep.get('stage')}: {rep.get('message')} FIX: {rep.get('fix')}")
            self.report({"ERROR"}, rep["message"])
        return {"FINISHED"}


class KILN_OT_export_log(bpy.types.Operator):
    bl_idname = "kiln.export_log"
    bl_label = "Export Debug Log"
    bl_description = "Write kiln-debug.txt with status, counters and recent log (attach to issues)"
    filepath: bpy.props.StringProperty(subtype="FILE_PATH", default="//kiln-debug.txt")
    def invoke(self, context, event):
        # default to blend dir; fall back to temp
        import os, tempfile
        try:
            d = bpy.path.abspath("//") or tempfile.gettempdir()
        except Exception:
            d = tempfile.gettempdir()
        self.filepath = os.path.join(d, "kiln-debug.txt")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}
    def execute(self, context):
        import os
        lines = []
        lines.append(f"Kiln debug — {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"status: {STATE.status}")
        lines.append(f"server={STATE.server_ws_base} room={STATE.room} user={STATE.user}")
        lines.append(f"seq={STATE.last_seq} rtt_ms={STATE.rtt_ms} sent={STATE.sent_count} recv={STATE.recv_count}")
        lines.append(f"users={sorted(STATE.users)} locks={STATE.engine.locks}")
        lines.append(f"diag={STATE.diag}")
        lines.append("--- log ---")
        lines.append(STATE.log.dump() or "(empty)")
        try:
            path = bpy.path.abspath(self.filepath)
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self.report({"INFO"}, f"Log saved: {path}")
            log("INFO", f"log exported to {path}")
        except Exception as e:
            self.report({"ERROR"}, f"Export failed: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class KILN_OT_clear(bpy.types.Operator):
    bl_idname = "kiln.clear_errors"
    bl_label = "Clear"
    bl_description = "Clear errors and log"
    def execute(self, context):
        STATE.errors.clear()
        STATE.log.clear()
        STATE.status = "Live in '%s' as %s" % (STATE.room, STATE.user) if STATE.connected else "Offline — press Connect"
        return {"FINISHED"}


def _selected_lock_info(context):
    """Return (holder_or_None, names) for current selection."""
    holders = set()
    names = []
    for o in getattr(context, "selected_objects", []):
        kid = o.get(KILN_ID_KEY)
        names.append(o.name)
        if kid and kid in STATE.engine.locks:
            holders.add(STATE.engine.locks[kid])
    holders.discard(None)
    if not holders:
        return None, names
    if holders == {STATE.user}:
        return STATE.user, names
    return ",".join(sorted(holders)), names


class KILN_PT_panel(bpy.types.Panel):
    bl_label = "Kiln"
    bl_idname = "KILN_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Kiln"

    def draw(self, context):
        sc = context.scene
        L = self.layout
        # 1. Connection (1-2-3 friendly)
        box = L.box()
        box.label(text="1 · Server → 2 · Room+Name → 3 · Connect", icon="INFO")
        box.prop(sc, "kiln_server", text="Server")
        box.prop(sc, "kiln_room", text="Room")
        row = box.row(align=True)
        row.prop(sc, "kiln_user", text="Name")
        row.prop(sc, "kiln_color", text="")
        icon = "LINKED" if STATE.connected else ("ERROR" if STATE.errors else "UNLINKED")
        box.label(text=STATE.status, icon=icon)
        r = box.row(align=True)
        r.operator("kiln.connect", icon="LINKED", text="Connect")
        r.operator("kiln.disconnect", icon="UNLINKED", text="")
        r.operator("kiln.test_connection", icon="CHECKMARK", text="Test")
        # live counters (debug at a glance)
        if STATE.connected or STATE.rtt_ms >= 0:
            L.label(text=f"seq {STATE.last_seq} · {STATE.rtt_ms}ms · ↑{STATE.sent_count} ↓{STATE.recv_count} · users {len(STATE.users)}", icon="NONE")
        # 2. Selection + locks (warn before you break things)
        holder, names = _selected_lock_info(context)
        if names:
            if holder and holder != STATE.user:
                b = L.box()
                b.alert = True
                b.label(text=f"Locked by {holder} — your edits may be overwritten", icon="LOCKED")
            elif holder == STATE.user:
                L.label(text="You hold the lock on selection", icon="LOCKED")
        L.label(text=f"Users ({len(STATE.users)}):")
        for name in sorted(STATE.users):
            L.label(text=f"• {name}")
        L.separator()
        r = L.row(align=True)
        r.operator("kiln.lock_selected", icon="LOCKED")
        r.operator("kiln.unlock_selected", icon="UNLOCKED")
        L.operator("kiln.push_mesh", icon="MESH_DATA")
        r = L.row(align=True)
        r.operator("kiln.push_snapshot", icon="EXPORT")
        r.operator("kiln.pull_snapshot", icon="IMPORT")
        L.operator("kiln.add_comment", icon="COMMENT")
        if STATE.comments:
            L.separator()
            L.label(text="Comments (latest):")
            for c in STATE.comments[-5:]:
                L.label(text=f"{c.get('from')}: {(c.get('body') or '')[:60]}")
        # 3. Troubleshooting (always visible, human fixes)
        L.separator()
        box = L.box()
        box.label(text="Troubleshooting", icon="QUESTION")
        if STATE.diag.get("message"):
            box.label(text=STATE.diag["message"][:80])
            if STATE.diag.get("fix"):
                box.label(text=f"Fix: {STATE.diag['fix'][:80]}")
        if STATE.errors:
            box.label(text=f"Last: {STATE.errors[-1][:90]}", icon="ERROR")
        else:
            box.label(text="No errors. Both Blenders: SAME server + SAME room, different Names.")
        row = box.row(align=True)
        row.operator("kiln.export_log", icon="TEXT", text="Export Log")
        row.operator("kiln.clear_errors", icon="X", text="Clear")
        if sc.kiln_show_log:
            box.label(text="Recent log:")
            for line in STATE.log.last(8):
                box.label(text=line[:90])


CLASSES = (KILN_OT_connect, KILN_OT_disconnect, KILN_OT_lock_selected,
           KILN_OT_unlock_selected, KILN_OT_push_mesh, KILN_OT_push_snapshot,
           KILN_OT_pull_snapshot, KILN_OT_add_comment, KILN_OT_test_connection,
           KILN_OT_export_log, KILN_OT_clear, KILN_PT_panel)


def register_ui():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.kiln_server = bpy.props.StringProperty(name="Server", default="ws://127.0.0.1:8000", description="Kiln server base, e.g. ws://127.0.0.1:8000")
    bpy.types.Scene.kiln_room = bpy.props.StringProperty(name="Room", default="demo", description="Same on all machines (case-insensitive)")
    bpy.types.Scene.kiln_user = bpy.props.StringProperty(name="User", default="artist", description="Must be unique per machine")
    bpy.types.Scene.kiln_color = bpy.props.StringProperty(name="Color", default="#e04f5e")
    bpy.types.Scene.kiln_show_log = bpy.props.BoolProperty(name="Show Log", default=False, description="Show recent debug log in panel")
    if not bpy.app.timers.is_registered(kiln_timer):
        bpy.app.timers.register(kiln_timer, persistent=True)


def unregister_ui():
    try:
        if bpy.app.timers.is_registered(kiln_timer):
            bpy.app.timers.unregister(kiln_timer)
    except Exception:
        pass
    disconnect_now()
    for c in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(c)
        except Exception:
            pass
    for p in ("kiln_server", "kiln_room", "kiln_user", "kiln_color", "kiln_show_log"):
        try:
            del bpy.types.Scene.__annotations__[p]
        except Exception:
            pass
