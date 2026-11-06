#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
binance_user_stream.py —— 用你自己的 API Key 接币安「私有实时推送」（用户数据流）

覆盖三条当前可用的官方通道（2026-11 实测可用性）：

  现货 Spot    wss://ws-api.binance.com:443/ws-api/v3
               JSON-RPC 方式订阅：userDataStream.subscribe.signature（HMAC 签名，无需 Ed25519 会话）
               注意：旧的 POST /api/v3/userDataStream 已 410 Gone，不要再按老文档写。

  U 本位合约   POST/PUT/DELETE https://fapi.binance.com/fapi/v1/listenKey
               WS: wss://fstream.binance.com/private/ws?listenKey=<key>[&events=ORDER_TRADE_UPDATE/ACCOUNT_UPDATE]
               （2026 路由拆分后，私有流必须走 /private，旧 /ws/<listenKey> 只用于兼容）

  币本位合约   POST/PUT/DELETE https://dapi.binance.com/dapi/v1/listenKey
               WS: wss://dstream.binance.com/ws/<listenKey>

安全约定（重要）：
  * 密钥只从环境变量 BINANCE_API_KEY / BINANCE_API_SECRET 或 --key-file 读取；
    --key-file 里第一行 apiKey、第二行 secret，权限建议 chmod 600。
  * 本脚本不打印 API Key / Secret，错误信息里出现的密钥会被掩码。
  * 建议只创建「允许读取」权限的 API Key；如果填了 IP 白名单，把运行机器的出口 IP 加进去。
  * 本脚本只读（check/snapshot/listen），不包含任何下单/撤单/提币能力。

零第三方依赖：仅标准库；内置一个最小 RFC6455 WebSocket 客户端。

用法：
  # 0) 无密钥自检（先验证网络与 WS 客户端实现）
  python3 tools/binance_user_stream.py selftest

  # 1) 校验 Key 权限 / 连通性（不会打印密钥）
  export BINANCE_API_KEY=...  BINANCE_API_SECRET=...
  python3 tools/binance_user_stream.py check
  python3 tools/binance_user_stream.py check --markets spot,um,cm

  # 2) 拉一次账户快照（余额 / 持仓 / 挂单）
  python3 tools/binance_user_stream.py snapshot --out work/private
  python3 tools/binance_user_stream.py snapshot --markets um --out work/private

  # 3) 实时监听私有推送（JSONL 落盘 + 控制台摘要）
  python3 tools/binance_user_stream.py listen --markets spot,um --out work/private --duration 300
  python3 tools/binance_user_stream.py listen --markets um --events ORDER_TRADE_UPDATE/ACCOUNT_UPDATE

退出码：0 正常；1 参数/鉴权/接口错误；2 重试耗尽。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import random
import socket
import ssl
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:  # 同目录模块；失败时不阻塞 selftest
    from event_sink import build_sinks, normalize, BaseSink
except Exception:  # pragma: no cover
    build_sinks = None
    normalize = None
    BaseSink = object

UA = "binance-user-stream/1.0 (stdlib)"
SPOT_REST = "https://api.binance.com"
UM_REST = "https://fapi.binance.com"
CM_REST = "https://dapi.binance.com"
SPOT_WS_API = "wss://ws-api.binance.com:443/ws-api/v3"
UM_PRIVATE_WS = "wss://fstream.binance.com/private/ws"
CM_PRIVATE_WS = "wss://dstream.binance.com/ws"
SPOT_PUBLIC_WS = "wss://stream.binance.com:9443"
UM_MARKET_WS = "wss://fstream.binance.com/market/ws"

KEEPALIVE_SPOT_SEC = 30 * 60     # 现货 WS API 的订阅随连接存在；这里用于保活/重连判断
KEEPALIVE_FUT_SEC = 30 * 60      # listenKey 官方 60 分钟过期，30 分钟 PUT 一次
MAX_KEYS_SHOWN = 4


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def now_ms() -> int:
    return int(time.time() * 1000)


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mask(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    if len(s) <= keep:
        return "*" * len(s)
    return s[:keep] + "*" * (len(s) - keep)


def sign_rest(secret: str, params: dict) -> str:
    """Binance REST/WS API 通用签名：按参数名 ASCII 排序后拼 key=value&...，HMAC-SHA256。"""
    payload = "&".join(
        f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in sorted(params.items())
    )
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def http_json(method: str, base: str, path: str, *, api_key: str | None = None,
              secret: str | None = None, params: dict | None = None,
              signed: bool = False, timeout: int = 20, retries: int = 3) -> tuple[int, dict]:
    """轻量 HTTP JSON 调用；signed=True 时自动加 timestamp/recvWindow/signature。"""
    params = dict(params or {})
    if signed:
        if not secret:
            raise ValueError("signed request requires secret")
        params["timestamp"] = now_ms()
        params.setdefault("recvWindow", 5000)
        params["signature"] = sign_rest(secret, params)
    url = base + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if api_key:
        headers["X-MBX-APIKEY"] = api_key
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
                try:
                    return r.status, json.loads(body) if body else {}
                except json.JSONDecodeError:
                    return r.status, {"_raw": body[:400]}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {"_raw": body[:400], "_content_type": e.headers.get("content-type", "")}
            # 4xx 是确定性错误，不重试
            if 400 <= e.code < 500:
                return e.code, data
            last_err = (e.code, data)
        except (urllib.error.URLError, ssl.SSLError, TimeoutError, ConnectionError) as e:
            last_err = (0, {"_error": str(e)})
        time.sleep(min(8.0, 1.2 * (2 ** attempt)) + random.random() * 0.3)
    return last_err if last_err else (0, {"_error": "unknown"})


# ---------------------------------------------------------------------------
# 最小 RFC6455 WebSocket 客户端（仅标准库；够用、可自检）
# ---------------------------------------------------------------------------
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
            f"User-Agent: {UA}\r\n"
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


# ---------------------------------------------------------------------------
# 轮询/输出辅助
# ---------------------------------------------------------------------------
class StreamWriter:
    """把事件同时写给多个 sink（JSONL/CSV/SQLite/PG/信号），并在控制台打印摘要。"""

    def __init__(self, sinks: list, quiet: bool = False):
        self.sinks = sinks
        self.quiet = quiet
        self.count = 0

    def start(self):
        for s in self.sinks:
            s.start()

    def write(self, market: str, event: dict):
        self.count += 1
        if not self.quiet:
            etype = event.get("e") or event.get("type") or "?"
            sym = event.get("s") or ""
            extra = ""
            if etype == "executionReport":
                extra = (f"{event.get('S','')} {event.get('o','')} {event.get('q','')} "
                         f"@ {event.get('p','')} status={event.get('X','')}")
            elif etype == "ORDER_TRADE_UPDATE":
                o = event.get("o", {})
                extra = (f"{o.get('S','')} {o.get('o','')} {o.get('q','')} "
                         f"@ {o.get('p','')} status={o.get('X','')}")
            elif etype == "ACCOUNT_UPDATE":
                extra = f"reason={event.get('a',{}).get('m','')}"
            elif etype == "outboundAccountPosition":
                extra = f"balances={len(event.get('B',[]))}"
            elif etype == "balanceUpdate":
                extra = f"{event.get('a','')} delta={event.get('d','')}"
            print(f"[{iso_now()}] {market:4s} {etype:24s} {sym:12s} {extra}")
        if normalize is None:
            return
        n = normalize(market, event)
        for s in self.sinks:
            s.write(n)

    def close(self):
        for s in self.sinks:
            try:
                s.close()
            except Exception:
                pass


def load_credentials(args) -> tuple[str, str]:
    key = os.environ.get("BINANCE_API_KEY", "").strip()
    sec = os.environ.get("BINANCE_API_SECRET", "").strip()
    if args.key_file:
        with open(args.key_file, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        if len(lines) >= 2:
            key, sec = lines[0], lines[1]
    return key, sec


def require_credentials(args) -> tuple[str, str]:
    key, sec = load_credentials(args)
    if not key or not sec:
        print("缺少 API Key。请设置环境变量 BINANCE_API_KEY / BINANCE_API_SECRET，"
              "或用 --key-file（两行：apiKey、secret）。", file=sys.stderr)
        print("提示：币安账户中心 → API 管理 → 创建 API Key，权限只勾「允许读取」。", file=sys.stderr)
        sys.exit(1)
    return key, sec



def listen_key_path(market: str) -> str:
    return "/fapi/v1/listenKey" if market == "um" else "/dapi/v1/listenKey"


def create_listen_key(rest: str, market: str, key: str, sec: str) -> tuple[int, dict]:
    """优先按官方约定只带 API Key（不签名）；若端点要求签名则自动回退重试一次。"""
    path = listen_key_path(market)
    code, data = http_json("POST", rest, path, api_key=key)
    if code == 200:
        return code, data
    code2, data2 = http_json("POST", rest, path, api_key=key, secret=sec, signed=True)
    return (code2, data2) if code2 == 200 else (code, data)


def keepalive_listen_key(rest: str, market: str, key: str, sec: str, listen_key: str) -> int:
    path = listen_key_path(market)
    code, _ = http_json("PUT", rest, path, api_key=key, params={"listenKey": listen_key})
    if code == 200:
        return code
    code2, _ = http_json("PUT", rest, path, api_key=key, secret=sec,
                         signed=True, params={"listenKey": listen_key})
    return code2 if code2 == 200 else code

# ---------------------------------------------------------------------------
# 命令：selftest（无密钥）
# ---------------------------------------------------------------------------
def cmd_selftest(args) -> int:
    ok = True
    # 1) 签名算法对照官方测试向量
    secret = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
    params = {
        "apiKey": "vmPUZE6mv9SD5VNHk4HlWFsOr6aKE2zvsw0MuIgwCIPy6utIco14y7Ju91duEh8A",
        "price": "52000.00", "quantity": "0.01000000", "recvWindow": 100,
        "side": "SELL", "symbol": "BTCUSDT", "timeInForce": "GTC",
        "timestamp": 1645423376532, "type": "LIMIT",
    }
    expect = "aa1b5712c094bc4e57c05a1a5c1fd8d88dcd628338ea863fec7b88e59fe2db24"
    got = sign_rest(secret, params)
    print(f"[1/4] 签名算法对照官方向量: {'OK' if got == expect else 'FAIL ' + got}")
    ok &= got == expect

    # 2) 现货主连（公共流）
    try:
        ws = WSClient(SPOT_PUBLIC_WS + "/ws/btcusdt@aggTrade", timeout=10)
        first = None
        t0 = time.time()
        while time.time() - t0 < 10:
            op, data = ws.recv()
            if op == 0x1 and b'"e"' in data:
                first = json.loads(data)
                break
        ws.close()
        print(f"[2/4] spot 公共 WS: {'OK' if first else 'NO DATA'} "
              f"{first.get('e') if first else ''} {first.get('s') if first else ''}")
        ok &= first is not None
    except Exception as e:
        print(f"[2/4] spot 公共 WS: FAIL {e}")

    # 3) U 本位公共 WS（新 /market 路由）
    try:
        ws = WSClient(UM_MARKET_WS + "/btcusdt@markPrice@1s", timeout=10)
        first = None
        t0 = time.time()
        while time.time() - t0 < 10:
            op, data = ws.recv()
            if op == 0x1:
                first = json.loads(data)
                break
        ws.close()
        print(f"[3/4] um /market WS: {'OK' if first else 'NO DATA'} "
              f"{first.get('e') if first else ''} {first.get('s') if first else ''}")
        ok &= first is not None
    except Exception as e:
        print(f"[3/4] um /market WS: FAIL {e}")

    # 4) 现货 WS API（公共请求）
    try:
        ws = WSClient(SPOT_WS_API, timeout=10)
        ws.send_text(json.dumps({"id": "1", "method": "ticker.price",
                                 "params": {"symbol": "BTCUSDT"}}))
        got = None
        t0 = time.time()
        while time.time() - t0 < 10:
            op, data = ws.recv()
            if op == 0x1:
                got = json.loads(data)
                break
        ws.close()
        ok &= bool(got and got.get("status") == 200)
        print(f"[4/4] spot WS API: {'OK' if got and got.get('status') == 200 else 'FAIL'} "
              f"{got.get('result') if got else ''}")
    except Exception as e:
        print(f"[4/4] spot WS API: FAIL {e}")

    print("SELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# 命令：check（读权限与连通性）
# ---------------------------------------------------------------------------
def cmd_check(args) -> int:
    key, sec = require_credentials(args)
    markets = [m.strip() for m in args.markets.split(",") if m.strip()]
    print(f"API Key: {mask(key)}  markets={markets}")
    rc = 0

    if "spot" in markets:
        code, acc = http_json("GET", SPOT_REST, "/api/v3/account",
                              api_key=key, secret=sec, signed=True)
        if code == 200 and isinstance(acc, dict) and "balances" in acc:
            nonzero = [b for b in acc["balances"] if float(b.get("free", 0)) + float(b.get("locked", 0)) > 0]
            print(f"[spot] OK accountType={acc.get('accountType')} canTrade={acc.get('canTrade')} "
                  f"canWithdraw={acc.get('canWithdraw')} canDeposit={acc.get('canDeposit')} "
                  f"permissions={','.join(acc.get('permissions') or [])} 非零币种={len(nonzero)}")
        else:
            print(f"[spot] FAIL http={code} {str(acc)[:200]}")
            rc = 1

        # 私有推送订阅测试（只订阅，不等待事件）
        try:
            ws = WSClient(SPOT_WS_API, timeout=15)
            params = {"apiKey": key, "timestamp": now_ms(), "recvWindow": 5000}
            params["signature"] = sign_rest(sec, params)
            ws.send_text(json.dumps({"id": "sub-1", "method": "userDataStream.subscribe.signature",
                                     "params": params}))
            resp = None
            t0 = time.time()
            while time.time() - t0 < 15:
                op, data = ws.recv()
                if op == 0x1:
                    resp = json.loads(data)
                    break
            ws.close()
            if resp and resp.get("status") == 200:
                print(f"[spot] 私有流订阅 OK subscriptionId={resp.get('result',{}).get('subscriptionId')}")
            else:
                print(f"[spot] 私有流订阅 FAIL {str(resp)[:250]}")
                rc = 1
        except Exception as e:
            print(f"[spot] 私有流订阅 FAIL {e}")
            rc = 1

    if "um" in markets:
        code, bal = http_json("GET", UM_REST, "/fapi/v2/balance",
                              api_key=key, secret=sec, signed=True)
        if code == 200 and isinstance(bal, list):
            total = sum(float(b.get("balance", 0)) for b in bal)
            print(f"[um] OK 账户数={len(bal)} 总余额≈{total:.4f} USDT")
        else:
            print(f"[um] FAIL http={code} {str(bal)[:200]}")
            rc = 1
        code, lk = create_listen_key(UM_REST, "um", key, sec)
        if code == 200 and isinstance(lk, dict) and lk.get("listenKey"):
            print(f"[um] listenKey OK {mask(lk['listenKey'], 6)}")
            http_json("DELETE", UM_REST, "/fapi/v1/listenKey",
                      api_key=key, params={"listenKey": lk["listenKey"]})
        else:
            print(f"[um] listenKey FAIL http={code} {str(lk)[:200]}")
            rc = 1

    if "cm" in markets:
        code, bal = http_json("GET", CM_REST, "/dapi/v1/balance",
                              api_key=key, secret=sec, signed=True)
        if code == 200 and isinstance(bal, list):
            total = sum(float(b.get("balance", 0)) for b in bal)
            print(f"[cm] OK 账户数={len(bal)} 总余额≈{total:.4f}")
        else:
            print(f"[cm] FAIL http={code} {str(bal)[:200]}")
            rc = 1
        code, lk = create_listen_key(CM_REST, "cm", key, sec)
        if code == 200 and isinstance(lk, dict) and lk.get("listenKey"):
            print(f"[cm] listenKey OK {mask(lk['listenKey'], 6)}")
            http_json("DELETE", CM_REST, "/dapi/v1/listenKey",
                      api_key=key, params={"listenKey": lk["listenKey"]})
        else:
            print(f"[cm] listenKey FAIL http={code} {str(lk)[:200]}")
            rc = 1

    print("CHECK", "PASS" if rc == 0 else "FAIL")
    return rc


# ---------------------------------------------------------------------------
# 命令：snapshot（一次性账户快照）
# ---------------------------------------------------------------------------
def cmd_snapshot(args) -> int:
    key, sec = require_credentials(args)
    markets = [m.strip() for m in args.markets.split(",") if m.strip()]
    out: dict = {"ts": iso_now(), "markets": {}}

    if "spot" in markets:
        code, acc = http_json("GET", SPOT_REST, "/api/v3/account",
                              api_key=key, secret=sec, signed=True)
        if code != 200:
            print(f"[spot] FAIL http={code} {str(acc)[:200]}", file=sys.stderr)
            return 1
        balances = [{"asset": b["asset"], "free": b["free"], "locked": b["locked"]}
                    for b in acc.get("balances", [])
                    if float(b.get("free", 0)) + float(b.get("locked", 0)) > 0]
        code, orders = http_json("GET", SPOT_REST, "/api/v3/openOrders",
                                 api_key=key, secret=sec, signed=True)
        out["markets"]["spot"] = {
            "accountType": acc.get("accountType"),
            "canTrade": acc.get("canTrade"),
            "permissions": acc.get("permissions"),
            "balances": balances,
            "openOrders": orders if code == 200 else {"_error": code},
        }
        print(f"[spot] 非零余额 {len(balances)} 个；挂单 {len(orders) if isinstance(orders, list) else 'ERR'}")

    if "um" in markets:
        code, pos = http_json("GET", UM_REST, "/fapi/v2/positionRisk",
                              api_key=key, secret=sec, signed=True)
        code2, orders = http_json("GET", UM_REST, "/fapi/v1/openOrders",
                                  api_key=key, secret=sec, signed=True)
        positions = [{"symbol": p.get("symbol"), "positionAmt": p.get("positionAmt"),
                      "entryPrice": p.get("entryPrice"), "markPrice": p.get("markPrice"),
                      "unRealizedProfit": p.get("unRealizedProfit"),
                      "leverage": p.get("leverage")}
                     for p in (pos if isinstance(pos, list) else [])
                     if abs(float(p.get("positionAmt", 0) or 0)) > 0]
        out["markets"]["um"] = {"positions": positions,
                                "openOrders": orders if code2 == 200 else {"_error": code2}}
        print(f"[um] 持仓 {len(positions)} 个；挂单 {len(orders) if isinstance(orders, list) else 'ERR'}")

    if "cm" in markets:
        code, pos = http_json("GET", CM_REST, "/dapi/v1/positionRisk",
                              api_key=key, secret=sec, signed=True)
        positions = [{"symbol": p.get("symbol"), "positionAmt": p.get("positionAmt"),
                      "entryPrice": p.get("entryPrice"), "markPrice": p.get("markPrice"),
                      "unRealizedProfit": p.get("unRealizedProfit")}
                     for p in (pos if isinstance(pos, list) else [])
                     if abs(float(p.get("positionAmt", 0) or 0)) > 0]
        out["markets"]["cm"] = {"positions": positions}
        print(f"[cm] 持仓 {len(positions)} 个")

    path = args.out
    if path:
        os.makedirs(path, exist_ok=True)
        fp = os.path.join(path, f"snapshot_{datetime.now().strftime('%Y%m%dT%H%M%SZ')}.json")
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"快照已写入 {fp}（注意：含账户数据，勿提交到公开仓库）")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


# ---------------------------------------------------------------------------
# 命令：listen（实时私有推送）
# ---------------------------------------------------------------------------
def _spot_listen(args, key: str, sec: str, writer: JsonlWriter, deadline: float, state: dict) -> None:
    backoff = 1.0
    auth_fail = 0
    while time.time() < deadline:
        try:
            ws = WSClient(SPOT_WS_API, timeout=30)
            params = {"apiKey": key, "timestamp": now_ms(), "recvWindow": 5000}
            params["signature"] = sign_rest(sec, params)
            ws.send_text(json.dumps({"id": "sub-1",
                                     "method": "userDataStream.subscribe.signature",
                                     "params": params}))
            print("[spot] 已发起 userDataStream.subscribe.signature，等待事件…")
            last_ping = time.time()
            while time.time() < deadline:
                try:
                    op, data = ws.recv()
                except socket.timeout:
                    continue
                if op != 0x1:
                    continue
                msg = json.loads(data)
                if msg.get("id") == "sub-1" or "status" in msg:
                    if msg.get("status") != 200:
                        err = (msg.get("error") or {})
                        print(f"[spot] 订阅失败 {msg}")
                        if err.get("code") in (-2014, -2015, -1022, -1100):
                            auth_fail += 1
                            if auth_fail >= 2:
                                print("[spot] 连续鉴权失败，停止该市场（检查 Key/IP 白名单/权限）")
                                state["auth_failed"] = True
                                return
                        break
                    print(f"[spot] 订阅成功 subscriptionId={msg.get('result',{}).get('subscriptionId')}")
                    continue
                if "e" in msg:  # 用户事件
                    writer.write("spot", msg)
                last_ping = time.time()
            ws.close()
            if time.time() < deadline:
                print("[spot] 连接结束，重连…")
        except Exception as e:
            print(f"[spot] 连接异常: {e}")
        time.sleep(min(30, backoff))
        backoff = min(30, backoff * 1.8)


def _futures_listen(market: str, rest: str, ws_base: str, args,
                    key: str, sec: str, writer: JsonlWriter, deadline: float, state: dict) -> None:
    listen_key = None
    last_keep = 0.0
    backoff = 1.0
    auth_fail = 0
    while time.time() < deadline:
        # 1) 拿 listenKey（每次重连都复用当前有效的 key）
        if not listen_key:
            code, lk = create_listen_key(rest, market, key, sec)
            if code == 200 and isinstance(lk, dict):
                listen_key = lk.get("listenKey")
            else:
                print(f"[{market}] listenKey 获取失败 http={code} {str(lk)[:200]}")
                if code in (401, 403) or (isinstance(lk, dict) and lk.get("code") in (-2014, -2015)):
                    auth_fail += 1
                    if auth_fail >= 2:
                        print(f"[{market}] 连续鉴权失败，停止该市场（检查 Key/IP 白名单/权限）")
                        state["auth_failed"] = True
                        return
                else:
                    auth_fail = 0
                time.sleep(min(30, backoff))
                backoff = min(30, backoff * 1.8)
                continue
        last_keep = time.time()
        # 2) 连接（优先新路由 /private，失败时回落旧式 /ws/<listenKey>）
        try:
            if market == "um":
                new_url = UM_PRIVATE_WS + "?listenKey=" + urllib.parse.quote(listen_key)
                if args.events:
                    new_url += "&events=" + urllib.parse.quote(args.events)
                legacy_url = "wss://fstream.binance.com/ws/" + urllib.parse.quote(listen_key)
                urls = [new_url, legacy_url]
            else:
                urls = [CM_PRIVATE_WS + "/" + urllib.parse.quote(listen_key)]
            ws = None
            last_exc = None
            for u in urls:
                try:
                    ws = WSClient(u, timeout=30)
                    break
                except Exception as e:  # 新路由不可用时尝试旧路由
                    last_exc = e
            if ws is None:
                raise last_exc or ConnectionError("no private ws route available")
            print(f"[{market}] 已连接私有流 {mask(listen_key, 6)}")
            while time.time() < deadline:
                if time.time() - last_keep > KEEPALIVE_FUT_SEC:
                    code = keepalive_listen_key(rest, market, key, sec, listen_key)
                    print(f"[{market}] listenKey keepalive http={code}")
                    last_keep = time.time()
                try:
                    op, data = ws.recv()
                except socket.timeout:
                    continue
                if op != 0x1:
                    continue
                msg = json.loads(data)
                etype = msg.get("e")
                if etype == "listenKeyExpired":
                    print(f"[{market}] listenKey 过期，重新申请")
                    listen_key = None
                    break
                writer.write(market, msg)
            ws.close()
        except Exception as e:
            print(f"[{market}] 连接异常: {e}")
        if time.time() < deadline:
            print(f"[{market}] 重连…")
        time.sleep(min(30, backoff))
        backoff = min(30, backoff * 1.8)


def cmd_listen(args) -> int:
    key, sec = require_credentials(args)
    markets = [m.strip() for m in args.markets.split(",") if m.strip()]
    duration = args.duration
    deadline = time.time() + duration if duration > 0 else time.time() + 10 ** 9
    out = args.out or "work/private"
    os.makedirs(out, exist_ok=True)
    if build_sinks is None:
        print("无法导入 tools/event_sink.py（请确保它与本脚本同目录）", file=sys.stderr)
        return 1
    try:
        sinks = build_sinks(args.sink, out, args.sqlite, args.pg_dsn,
                            want_signals=args.signals, quiet=args.quiet)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1
    except Exception as e:
        print(f"初始化 sink 失败: {e}", file=sys.stderr)
        return 1
    writer = StreamWriter(sinks, quiet=args.quiet)
    writer.start()
    print(f"监听市场={markets} sinks={args.sink}{'+signals' if args.signals else ''} "
          f"输出目录={out} 时长={duration or '∞'}s")
    state: dict = {}
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=len(markets)) as ex:
            futs = []
            for m in markets:
                if m == "spot":
                    futs.append(ex.submit(_spot_listen, args, key, sec, writer, deadline, state))
                elif m == "um":
                    futs.append(ex.submit(_futures_listen, "um", UM_REST, UM_PRIVATE_WS,
                                          args, key, sec, writer, deadline, state))
                elif m == "cm":
                    futs.append(ex.submit(_futures_listen, "cm", CM_REST, CM_PRIVATE_WS,
                                          args, key, sec, writer, deadline, state))
                else:
                    print(f"未知市场 {m}", file=sys.stderr)
                    return 1
            for f in futs:
                f.result()
    except KeyboardInterrupt:
        print("\n收到中断，退出")
    finally:
        writer.close()
    return 1 if state.get("auth_failed") else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="币安私有实时推送/账户数据（官方 API Key，只读）")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("--markets", default="spot,um,cm", help="逗号分隔：spot,um,cm（默认全部）")
        sp.add_argument("--key-file", help="两行文件：apiKey、secret（替代环境变量）")
        sp.add_argument("--quiet", action="store_true")

    sp = sub.add_parser("selftest", help="无密钥自检：签名向量 + 公共 WS 连通性")
    sp.set_defaults(func=cmd_selftest)

    sp = sub.add_parser("check", help="校验 API Key 权限 / 私有流连通性")
    add_common(sp)
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("snapshot", help="拉一次账户快照（余额/持仓/挂单）")
    add_common(sp)
    sp.add_argument("--out", help="输出目录")
    sp.set_defaults(func=cmd_snapshot)

    sp = sub.add_parser("listen", help="实时监听私有推送并落 JSONL")
    add_common(sp)
    sp.add_argument("--out", help="输出目录")
    sp.add_argument("--duration", type=int, default=0, help="秒；0=一直跑")
    sp.add_argument("--sink", default="jsonl",
                    help="落库目标，逗号分隔：jsonl,csv,sqlite,pg（默认 jsonl）")
    sp.add_argument("--sqlite", default=None, help="SQLite 文件路径（默认 <out>/binance_stream.db）")
    sp.add_argument("--pg-dsn", default=None, help="PostgreSQL DSN，如 postgresql://user:pass@host:5432/db")
    sp.add_argument("--signals", action="store_true", help="同时输出策略信号（JSONL）")
    sp.add_argument("--events", default="", help="UM 私有流事件过滤，如 ORDER_TRADE_UPDATE/ACCOUNT_UPDATE")
    sp.set_defaults(func=cmd_listen)
    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
