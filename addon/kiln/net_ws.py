"""Stdlib-only WebSocket client for Blender (no pip deps).

RFC6455 minimal client: handshake, masked text frames, ping/pong, close.
Thread-safe: `send()` from any thread, incoming frames → `on_frame` callback
in the reader thread. The addon marshals to Blender main thread via queue.

Tested against kiln-server + RFC6455 vectors.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import queue
import socket
import ssl
import struct
import threading
import urllib.parse

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WSError(Exception):
    pass


class KilnWS:
    def __init__(self, url: str, on_frame=None, on_close=None):
        self.url = url
        self.on_frame = on_frame or (lambda msg: None)
        self.on_close = on_close or (lambda reason: None)
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._send_lock = threading.Lock()
        self.inbox: queue.Queue[dict] = queue.Queue()

    # -- connection --
    def connect(self, timeout: float = 10.0):
        u = urllib.parse.urlparse(self.url)
        assert u.scheme in ("ws", "wss"), f"bad scheme {u.scheme}"
        host, port = u.hostname or "127.0.0.1", u.port or (443 if u.scheme == "wss" else 80)
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        sock = socket.create_connection((host, port), timeout=timeout)
        if u.scheme == "wss":
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
               f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        sock.sendall(req.encode())
        # read headers until blank line
        buf = b""
        sock.settimeout(timeout)
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise WSError("handshake: connection closed")
            buf += chunk
        head = buf.split(b"\r\n\r\n", 1)[0].decode("latin1")
        if "101" not in head.split("\r\n", 1)[0]:
            raise WSError(f"handshake failed: {head[:200]}")
        accept = None
        for line in head.split("\r\n"):
            if line.lower().startswith("sec-websocket-accept:"):
                accept = line.split(":", 1)[1].strip()
        expect = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        if accept != expect:
            raise WSError("handshake: bad accept key")
        sock.settimeout(30.0)
        self._sock = sock
        self._stop.clear()
        self._thread = threading.Thread(target=self._reader, daemon=True, name="kiln-ws")
        self._thread.start()

    def close(self):
        self._stop.set()
        try:
            self._send_close(1000, "bye")
        except Exception:
            pass
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass

    # -- send --
    def send(self, obj: dict):
        data = json.dumps(obj).encode("utf-8")
        self._send_frame(0x1, data)

    def _send_frame(self, opcode: int, data: bytes):
        with self._send_lock:
            sock = self._sock
            if sock is None:
                raise WSError("not connected")
            mask = os.urandom(4)
            n = len(data)
            hdr = bytes([0x80 | opcode])
            if n < 126:
                hdr += struct.pack("!B", 0x80 | n)
            elif n < (1 << 16):
                hdr += struct.pack("!B", 0x80 | 126) + struct.pack("!H", n)
            else:
                hdr += struct.pack("!B", 0x80 | 127) + struct.pack("!Q", n)
            masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            try:
                sock.sendall(hdr + mask + masked)
            except OSError as e:
                raise WSError(str(e))

    def _send_close(self, code: int = 1000, reason: str = ""):
        try:
            self._send_frame(0x8, struct.pack("!H", code) + reason.encode())
        except Exception:
            pass

    def _send_pong(self, data: bytes):
        try:
            with self._send_lock:
                sock = self._sock
                if sock is None:
                    return
                mask = os.urandom(4)
                hdr = bytes([0x80 | 0xA, 0x80 | len(data)]) if len(data) < 126 else None
                if hdr is None:
                    return
                masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
                sock.sendall(hdr + mask + masked)
        except Exception:
            pass

    # -- reader --
    def _recvn(self, n: int) -> bytes:
        assert self._sock is not None
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise WSError("connection closed")
            buf += chunk
        return buf

    def _reader(self):
        try:
            while not self._stop.is_set():
                try:
                    b1 = self._recvn(1)[0]
                    b2 = self._recvn(1)[0]
                except (WSError, OSError, socket.timeout):
                    break
                fin = bool(b1 & 0x80)
                opcode = b1 & 0x0F
                masked = bool(b2 & 0x80)
                length = b2 & 0x7F
                if length == 126:
                    length = struct.unpack("!H", self._recvn(2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", self._recvn(8))[0]
                mask = self._recvn(4) if masked else None
                payload = self._recvn(length) if length else b""
                if mask:
                    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
                if opcode == 0x1:  # text
                    try:
                        msg = json.loads(payload.decode("utf-8"))
                    except ValueError:
                        continue
                    self.inbox.put(msg)
                    try:
                        self.on_frame(msg)
                    except Exception:
                        pass
                elif opcode == 0x9:  # ping
                    self._send_pong(payload)
                elif opcode == 0x8:  # close
                    break
                elif opcode == 0xA:  # pong
                    pass
                if not fin:
                    # v0.1: no fragmentation support beyond single frame
                    continue
        finally:
            try:
                self.on_close("closed")
            except Exception:
                pass
