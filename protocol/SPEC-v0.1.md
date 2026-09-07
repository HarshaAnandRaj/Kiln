# Kiln Wire Protocol — SPEC v0.1 (normative)

Version: `0.1.0` — Transport: WebSocket, JSON (UTF-8), one object per frame.

## 1. URLs

- `WS  /v1/rooms/{room}/ws?user={name}&client={addon_version}`
- `GET /healthz` → `{"ok":true,"version":"0.1.0"}`
- `GET /v1/rooms/{room}/snapshot` → latest snapshot
- `POST /v1/rooms/{room}/snapshot` → store snapshot
- `GET /v1/rooms/{room}/ops?since={seq}&limit={n}` → op replay

Room IDs: `[a-zA-Z0-9_-]{1,64}`. User names: 1–32 chars. Server lowercases room.

## 2. Envelope

All frames:

```json
{"t": "<type>", "room": "demo", "from": "anand", "ts": 1725.123, "payload": {...}}
```

`t` ∈ `hello|welcome|op|presence|lock|unlock|lock_granted|lock_denied|comment|snapshot_push|snapshot|snapshot_request|error|bye`.

`ts` = client unix time float. Server adds `seq` (int, per-room monotonic from 1) and `server_ts` on broadcast.

## 3. hello / welcome

Client → Server:

```json
{"t":"hello","room":"demo","from":"anand","payload":{"client":"0.1.0","last_seq":0,"color":"#e04f5e"}}
```

Server → Client (`welcome`):

```json
{"t":"welcome","room":"demo","from":"server","payload":{"you":"anand","seq":42,"users":[{"name":"bob","color":"#3fa9f5"}],"locks":{"<kiln_id>":"bob"},"snapshot_seq":40}}
```

Client must then `snapshot_request` if `last_seq < snapshot_seq`, else fetch `/ops?since=last_seq`.

## 4. op

Client → Server (no `seq`, server assigns):

```json
{
  "t":"op","room":"demo","from":"anand",
  "payload":{
    "op_id":"uuid7",
    "kind":"transform",
    "kiln_id":"uuid-stable-per-object",
    "base_seq":42,
    "data":{
      "loc":[1,2,3],"rot_euler":[0,0,1.57],"rot_mode":"XYZ",
      "scale":[1,1,1],"name":"Cube","visible":true
    }
  }
}
```

Server broadcast adds: `"seq":43,"server_ts":...,"from":"anand"`.

### 4.1 Op kinds v0.1

- `object.upsert`: create or ensure object. `data: {obj_type: MESH|EMPTY|LIGHT|CAMERA|CURVE, name, ...transform fields, parent_kiln_id?}`
- `object.remove`: `data: {}` — tombstone by `kiln_id`.
- `transform`: `data: {loc?, rot_euler?, rot_quaternion?, rot_mode?, scale?, name?, visible?, parent_kiln_id?}` — partial allowed, LWW per field.
- `mesh.replace`: `data: {verts: [[x,y,z]...], loops?: [...], polys?: [[i,j,k]...], materials?: [...]}` — full replace, cap 50k verts. Use only on edit exit / manual push.
- `material.assign`: `data: {slot:0, mat_name:"Red", color:[1,0,0,1]}`
- `collection.link`: `data: {collection:"Collection", linked:true}`

Unknown `kind` → server replies `error {code:"unknown_kind"}` but still assigns seq? No — rejected, no seq.

### 4.2 Ordering + conflicts

- Server is authoritative: first-seen wins seq order, later seq wins (LWW).
- If `kiln_id` is locked by other user and `from != holder`, server still broadcasts but clients SHOULD warn; OR server may reject `transform|mesh.replace` with `lock_denied` if `strict_locks` room flag on (default off in v0.1 — soft locks).
- Echo suppression: clients MUST drop incoming `op` whose `payload.op_id` is in sent-set (TTL 5 min).
- `base_seq` informational; server does NOT do OT in v0.1.

## 5. presence

Broadcast at 2 Hz max, on change immediately:

```json
{"t":"presence","payload":{"color":"#e04f5e","selected":["<kiln_id>"],"cursor":[1,2,3],"mode":"OBJECT","view":"USER"}}
```

Server keeps last per user, rebroadcasts to room (no seq), expires after 10s.

## 6. lock / unlock

```json
{"t":"lock","payload":{"kiln_id":"...","want":true}}
{"t":"unlock","payload":{"kiln_id":"..."}}
```

Server replies unicast `lock_granted|lock_denied`, then broadcasts `lock` presence to room:

```json
{"t":"lock","payload":{"kiln_id":"...","holder":"anand_or_null"}}
```

Locks auto-release on disconnect.

## 7. comment / snapshot

```json
{"t":"comment","payload":{"id":"uuid","kiln_id_or_null":null,"at":[x,y,z],"body":"bevel this?","reply_to":null}}
{"t":"snapshot_request","payload":{}}
{"t":"snapshot_push","payload":{"seq_hint":42,"scene":{"objects":[...]}}}
{"t":"snapshot","payload":{"seq":42,"scene":{"objects":[...]}}}
```

Snapshot `scene.objects[]`: `{"kiln_id","name","obj_type","loc","rot_euler","rot_mode","scale","visible","parent_kiln_id","mesh?":mesh.replace data}`.

## 8. error / bye

```json
{"t":"error","payload":{"code":"mesh_too_large","detail":"50k cap","op_id":"..."}}
{"t":"bye","payload":{"reason":"quit"}}
```

Codes: `bad_room|bad_user|unknown_kind|mesh_too_large|rate_limited|stale|internal`.

## 9. Limits (v0.1)

- Max frame 4 MB. Max mesh 50k verts. Max ops log 10k/room (older trimmed).
- Rate: 30 ops/s per client burst, then `rate_limited`.
- Heartbeat: server ping every 20s, client must pong / send presence.

## 10. Compatibility

- `client` semver in hello. Server `"min_client":"0.1.0"`. If older → `error {code:"upgrade_required"}` + close 4400.
- Additive fields allowed; clients MUST ignore unknown fields.

Test vector: see `examples/two_cubes_sync.py` and `server/tests/test_protocol.py`.
