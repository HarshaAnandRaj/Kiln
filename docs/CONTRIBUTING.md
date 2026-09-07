# Contributing to Kiln

## Setup

```powershell
pip install -e ./server[dev]
pytest server/tests -q
python examples/two_cubes_sync.py  # needs server running
```

Blender addon dev: symlink `addon/kiln` into Blender scripts dir, or zip + Install from Disk. Test with `pytest addon/tests -q` (uses `bpy_stub`, no Blender needed).

## Rules (to stay usable)

1. Protocol change → update `protocol/SPEC-v0.1.md` + `schema.json` + `server/tests/test_protocol.py` in same PR.
2. Never call `bpy` off main thread. Net → queue → timer.
3. Every op needs `op_id` + echo-suppression test.
4. Mesh changes must respect 50k cap + throttle.
5. GPL for `addon/`, Apache-2.0 for `server/` — don't mix imports.

## PR checklist

- [ ] `pytest server/tests addon/tests` green
- [ ] Manual 2-Blender test: cube move, rename, lock, comment, snapshot round-trip
- [ ] Docs updated if wire changed
