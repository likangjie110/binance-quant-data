"""最小 RFC6455 WebSocket 客户端（仅标准库；支持 ping/pong、分片、close）。"""
from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
import urllib.parse

from .config import USER_AGENT


class WSClient:
    def __init__(self, url: str, timeout: float = 30.0, verbose: bool = False):
        self.url = url
        self.verbose = verbose
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "wss":
            raise ValueError("only wss:// supported")
        host = parts.hostname
        port = parts.port or 443
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        self.host, self.port = host, port
        raw = socket.create_connection((host, port), timeout=timeout)
        ctx = ssl.create_default_context()
        self.sock = ctx.wrap_socket(raw, server_hostname=host)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"User-Agent: {USER_AGENT}\r\n"
            "\r\n"
        )
        self.sock.sendall(req.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake closed")
            head += chunk
        header, _, rest = head.partition(b"\r\n\r\n")
        status_line = header.split(b"\r\n", 1)[0].decode("latin1")
        if " 101 " not in status_line:
            raise ConnectionError(f"websocket handshake failed: {status_line[:120]}")
        accept = None
        for line in header.decode("latin1").split("\r\n")[1:]:
            if line.lower().startswith("sec-websocket-accept:"):
                accept = line.split(":", 1)[1].strip()
        expect = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        if accept != expect:
            raise ConnectionError("websocket accept mismatch")
        self._buf = rest
        self._closed = False

    # ---- 低层 ----
    def _read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(max(4096, n - len(self._buf)))
            if not chunk:
                raise ConnectionError("socket closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send_frame(self, opcode: int, payload: bytes):
        header = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < (1 << 16):
            header += bytes([0x80 | 126]) + struct.pack("!H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack("!Q", n)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def send_text(self, s: str):
        self._send_frame(0x1, s.encode("utf-8"))

    def send_pong(self, data: bytes = b""):
        self._send_frame(0xA, data)

    def recv(self) -> tuple[int, bytes]:
        """返回 (opcode, payload)；自动回 pong，close 时抛 ConnectionError。"""
        frags: list[bytes] = []
        frag_opcode = None
        while True:
            b1, b2 = self._read_exact(2)
            fin = bool(b1 & 0x80)
            opcode = b1 & 0x0F
            masked = bool(b2 & 0x80)
            ln = b2 & 0x7F
            if ln == 126:
                ln = struct.unpack("!H", self._read_exact(2))[0]
            elif ln == 127:
                ln = struct.unpack("!Q", self._read_exact(8))[0]
            mask_key = self._read_exact(4) if masked else b""
            payload = self._read_exact(ln) if ln else b""
            if masked:
                payload = bytes(c ^ mask_key[i % 4] for i, c in enumerate(payload))
            if opcode == 0x9:  # ping
                self.send_pong(payload)
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode == 0x8:  # close
                self._closed = True
                raise ConnectionError(f"websocket closed (code={struct.unpack('!H', payload[:2])[0] if len(payload)>=2 else '?'})")
            if opcode == 0x0:  # continuation
                frags.append(payload)
                if fin:
                    data = b"".join(frags)
                    return frag_opcode or 0x1, data
                continue
            if not fin:
                frag_opcode = opcode
                frags = [payload]
                continue
            return opcode, payload

    def close(self):
        try:
            if not self._closed:
                self._send_frame(0x8, struct.pack("!H", 1000))
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass
        self._closed = True
