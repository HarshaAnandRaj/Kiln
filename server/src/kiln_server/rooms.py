# SPDX-License-Identifier: Apache-2.0
# Copyright (C) Kiln Contributors -- see LICENSE-SERVER
"""Room state: authoritative seq, op log, locks, presence, comments, snapshot."""
from __future__ import annotations
import asyncio
import time
from collections import deque, defaultdict

MAX_OPS = 10_000


class RoomState:
    def __init__(self, name: str):
        self.name = name
        self.lock = asyncio.Lock()
        self.seq = 0
        self.ops: deque[dict] = deque(maxlen=MAX_OPS)
        self.objects: dict[str, dict] = {}      # kiln_id -> last op frame
        self.locks: dict[str, str] = {}         # kiln_id -> user
        self.presence: dict[str, dict] = {}     # user -> presence payload
        self.user_colors: dict[str, str] = {}
        self.comments: list[dict] = []
        self.snapshot: dict | None = None       # {"seq":int,"scene":dict}
        self.connections: set = set()           # active websockets
        self.rate: dict[str, list[float]] = defaultdict(list)

    def check_rate(self, user: str, limit: int = 30, window: float = 1.0) -> bool:
        now = time.time()
        q = self.rate[user]
        q[:] = [t for t in q if now - t < window]
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    async def next_seq(self) -> int:
        async with self.lock:
            self.seq += 1
            return self.seq

    async def append_op(self, frame: dict) -> dict:
        async with self.lock:
            self.seq += 1
            frame = {**frame, "seq": self.seq, "server_ts": time.time()}
            self.ops.append(frame)
            kiln_id = frame["payload"].get("kiln_id")
            if kiln_id:
                self.objects[kiln_id] = frame
            return frame

    async def ops_since(self, since: int, limit: int = 500) -> list[dict]:
        async with self.lock:
            return [o for o in self.ops if (o.get("seq") or 0) > since][:limit]


class RoomManager:
    def __init__(self):
        self._rooms: dict[str, RoomState] = {}
        self._guard = asyncio.Lock()

    async def get(self, name: str) -> RoomState:
        name = name.lower()
        async with self._guard:
            room = self._rooms.get(name)
            if room is None:
                room = RoomState(name)
                self._rooms[room.name] = room
            return room

    def get_nowait(self, name: str) -> RoomState | None:
        return self._rooms.get(name.lower())
