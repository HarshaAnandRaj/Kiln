"""Scene scan → ops, ops → scene. bpy calls isolated in adapters so core is testable."""
from __future__ import annotations
from dataclasses import dataclass, field

from .core_ids import KILN_ID_KEY
from .proto import fingerprint_transform
from . import mesh_sync


@dataclass
class ObjSnap:
    kiln_id: str
    name: str
    obj_type: str
    loc: tuple
    rot: tuple
    rot_mode: str = "XYZ"
    rot_quat: tuple | None = None
    scale: tuple = (1, 1, 1)
    visible: bool = True
    parent_kiln_id: str | None = None
    mesh_fp: tuple = ()


def snap_fingerprint(s: ObjSnap) -> tuple:
    return (s.name, s.obj_type,
            fingerprint_transform(s.loc, s.rot, s.scale, s.name, s.visible),
            s.parent_kiln_id, s.mesh_fp)


class SyncEngine:
    """Diff cache + echo suppression + lock table. No bpy here."""

    def __init__(self):
        self.cache: dict[str, tuple] = {}   # kiln_id -> fingerprint
        self.snaps: dict[str, ObjSnap] = {}
        self.sent_op_ids: set[str] = set()
        self.seen_seq: int = 0
        self.locks: dict[str, str] = {}     # kiln_id -> holder
        self.users: dict[str, str] = {}     # name -> color
        self.suppress: bool = False         # True while applying remote ops

    def mark_sent(self, op_id: str):
        self.sent_op_ids.add(op_id)
        if len(self.sent_op_ids) > 2000:
            self.sent_op_ids = set(list(self.sent_op_ids)[-1000:])

    def is_echo(self, op_id: str) -> bool:
        return op_id in self.sent_op_ids

    def diff(self, current: dict[str, ObjSnap]):
        """Compare current {kiln_id: snap} vs cache. Returns (upserts, removes)."""
        upserts: list[ObjSnap] = []
        for kid, snap in current.items():
            fp = snap_fingerprint(snap)
            if self.cache.get(kid) != fp:
                upserts.append(snap)
        removes = [kid for kid in self.cache if kid not in current]
        return upserts, removes

    def commit(self, current: dict[str, ObjSnap]):
        self.cache = {kid: snap_fingerprint(s) for kid, s in current.items()}
        self.snaps = dict(current)

    def apply_remote_update(self, current: dict[str, ObjSnap], kiln_id: str, snap: ObjSnap):
        current[kiln_id] = snap
        self.cache[kiln_id] = snap_fingerprint(snap)

    def apply_remote_remove(self, current: dict[str, ObjSnap], kiln_id: str):
        current.pop(kiln_id, None)
        self.cache.pop(kiln_id, None)


# -- bpy adapters (only called from Blender main thread) --
def scan_bpy_scene() -> dict[str, ObjSnap]:
    import bpy
    out: dict[str, ObjSnap] = {}
    for obj in bpy.data.objects:
        # skip Kiln presence empties
        if obj.name.startswith("KILN_presence_"):
            continue
        kid = obj.get(KILN_ID_KEY)
        if not isinstance(kid, str) or not kid:
            continue  # ids assigned by ensure pass
        try:
            loc = tuple(obj.location)
            rot_mode = getattr(obj, "rotation_mode", "XYZ")
            if rot_mode == "QUATERNION":
                rot = tuple(obj.rotation_quaternion)
            else:
                rot = tuple(obj.rotation_euler)
            scale = tuple(obj.scale)
            visible = bool(obj.visible_get())
            parent = obj.parent
            parent_kid = parent.get(KILN_ID_KEY) if parent else None
            if not isinstance(parent_kid, str):
                parent_kid = None
            mesh_fp: tuple = ()
            if obj.type == "MESH" and obj.data is not None:
                try:
                    n = len(obj.data.vertices)
                    mesh_fp = (n, getattr(obj.data, "update_tag", lambda: None) and n)
                except Exception:
                    mesh_fp = ()
            out[kid] = ObjSnap(kiln_id=kid, name=obj.name, obj_type=obj.type,
                               loc=loc, rot=rot, rot_mode=rot_mode, scale=scale,
                               visible=visible, parent_kiln_id=parent_kid, mesh_fp=mesh_fp)
        except Exception:
            continue
    return out


def ensure_bpy_ids() -> int:
    import bpy
    from .core_ids import ensure_id
    n = 0
    for obj in bpy.data.objects:
        if obj.name.startswith("KILN_presence_"):
            continue
        _, created = ensure_id(obj)
        if created:
            n += 1
    return n


def apply_op_bpy(op_payload: dict, kiln_id: str) -> str:
    """Apply a remote op to bpy scene. Returns status string. Main thread only."""
    import bpy
    kind = op_payload.get("kind")
    data = op_payload.get("data") or {}
    if kind == "object.remove":
        for obj in list(bpy.data.objects):
            if obj.get(KILN_ID_KEY) == kiln_id:
                bpy.data.objects.remove(obj, do_unlink=True)
                return "removed"
        return "missing"
    if kind in ("object.upsert", "transform"):
        target = None
        for obj in bpy.data.objects:
            if obj.get(KILN_ID_KEY) == kiln_id:
                target = obj
                break
        if target is None:
            if kind == "object.upsert":
                otype = data.get("obj_type", "EMPTY")
                try:
                    if otype == "MESH":
                        me = bpy.data.meshes.new(data.get("name", "KilnObj") + "_mesh")
                        target = bpy.data.objects.new(data.get("name", "KilnObj"), me)
                        # link
                        coll = bpy.context.scene.collection
                        coll.objects.link(target)
                    elif otype == "LIGHT":
                        ld = bpy.data.lights.new(data.get("name", "KilnLight"), "POINT")
                        target = bpy.data.objects.new(data.get("name", "KilnLight"), ld)
                        bpy.context.scene.collection.objects.link(target)
                    elif otype == "CAMERA":
                        cd = bpy.data.cameras.new(data.get("name", "KilnCam"))
                        target = bpy.data.objects.new(data.get("name", "KilnCam"), cd)
                        bpy.context.scene.collection.objects.link(target)
                    else:
                        target = bpy.data.objects.new(data.get("name", "KilnEmpty"), None)
                        bpy.context.scene.collection.objects.link(target)
                    target[KILN_ID_KEY] = kiln_id
                except Exception as e:
                    return f"create_failed: {e}"
            else:
                return "missing"
        try:
            if "name" in data and data["name"] and target.name != data["name"]:
                try:
                    target.name = data["name"]
                except Exception:
                    pass
            if "loc" in data:
                target.location = data["loc"]
            if "rot_mode" in data:
                try:
                    target.rotation_mode = data["rot_mode"]
                except Exception:
                    pass
            if "rot_euler" in data and getattr(target, "rotation_mode", "XYZ") != "QUATERNION":
                target.rotation_euler = data["rot_euler"]
            if "rot_quaternion" in data and getattr(target, "rotation_mode", "") == "QUATERNION":
                target.rotation_quaternion = data["rot_quaternion"]
            if "scale" in data:
                target.scale = data["scale"]
            if "visible" in data:
                try:
                    target.hide_viewport = not bool(data["visible"])
                except Exception:
                    pass
            if "parent_kiln_id" in data:
                pk = data["parent_kiln_id"]
                if pk:
                    for o in bpy.data.objects:
                        if o.get(KILN_ID_KEY) == pk:
                            target.parent = o
                            break
                else:
                    target.parent = None
            return "applied"
        except Exception as e:
            return f"apply_failed: {e}"
    if kind == "mesh.replace":
        for obj in bpy.data.objects:
            if obj.get(KILN_ID_KEY) == kiln_id:
                ok = mesh_sync.apply_bpy_mesh(obj, data)
                return "mesh_applied" if ok else "mesh_failed"
        return "missing"
    if kind == "material.assign":
        return "mat_ignored_v01"
    if kind == "collection.link":
        return "coll_ignored_v01"
    return f"unknown_kind:{kind}"
