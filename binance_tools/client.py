"""统一的 HTTP 客户端：公开 GET（限频/退避/权重）与私有签名请求（listenKey/账户）。"""
from __future__ import annotations

import json
import random
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from .common import log, now_ms
from .config import USER_AGENT
from .signing import sign_rest


class BinanceAPIError(RuntimeError):
    """接口返回非 200 且不可重试（参数错误、符号不存在等）。"""

    def __init__(self, status, code, msg, url):
        self.status, self.code, self.msg, self.url = status, code, msg, url
        super().__init__(f"HTTP {status} code={code} msg={msg} ({url})")


class RetryExhausted(RuntimeError):
    pass


# ----------------------------------------------------------------------------
# HTTP 客户端
# ----------------------------------------------------------------------------
class BinanceClient:
    """带限频感知、指数退避重试的只读 GET 客户端。"""

    def __init__(self, timeout=20, max_retries=5, proxy=None, user_agent=USER_AGENT,
                 min_interval=0.12, verbose=True):
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.verbose = verbose
        handlers = [urllib.request.HTTPSHandler(context=ssl.create_default_context())]
        if proxy:
            handlers.insert(0, urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        self.opener = urllib.request.build_opener(*handlers)
        self._last_call = 0.0
        self.requests = 0
        self.last_weight = {}          # host -> 最近一次 X-MBX-USED-WEIGHT-1M
        self.last_headers = {}         # host -> 关注的响应头
        self._limit = {}               # host -> 该市场官方 1 分钟权重上限

    def set_weight_limit(self, host, limit):
        self._limit[host] = int(limit)

    def _pace(self):
        wait = self.min_interval - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def _observe(self, url, headers):
        host = urllib.parse.urlsplit(url).netloc
        h = {k.lower(): v for k, v in headers.items()}
        used = h.get("x-mbx-used-weight-1m") or h.get("x-mbx-used-weight")
        self.last_headers[host] = {
            k: h.get(k) for k in ("x-mbx-used-weight-1m", "x-mbx-used-weight",
                                  "retry-after", "x-mbx-uuid", "server", "x-cache")
            if h.get(k) is not None
        }
        if used is None:
            return
        try:
            used = int(used)
        except ValueError:
            return
        self.last_weight[host] = used
        limit = self._limit.get(host)
        if not limit:
            return
        ratio = used / float(limit)
        if ratio >= 0.95:
            if self.verbose:
                log(f"  ! 权重 {used}/{limit} ({ratio:.0%}) 逼近上限，休眠 25s 让路")
            time.sleep(25)
        elif ratio >= 0.85:
            if self.verbose:
                log(f"  ! 权重 {used}/{limit} ({ratio:.0%}) 偏高，休眠 4s 让路")
            time.sleep(4)

    def get(self, base, path, params=None, allow_retry=True):
        """返回 (obj, meta)。obj 为已解析 JSON，meta 含 http 状态/权重/耗时。"""
        url = base + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)
        attempt = 0
        while True:
            attempt += 1
            self._pace()
            t0 = time.time()
            req = urllib.request.Request(url, headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            })
            try:
                with self.opener.open(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    self.requests += 1
                    self._observe(url, resp.headers)
                    meta = {
                        "status": resp.status, "url": url,
                        "elapsed_ms": round((time.time() - t0) * 1000),
                        "used_weight_1m": self.last_weight.get(urllib.parse.urlsplit(url).netloc),
                        "attempt": attempt,
                    }
                    if self.verbose:
                        w = meta["used_weight_1m"]
                        log(f"[{resp.status}] {path} {meta['elapsed_ms']}ms"
                            + (f" weight={w}" if w is not None else ""))
                    return json.loads(raw.decode("utf-8", "replace")), meta

            except urllib.error.HTTPError as e:
                raw = e.read()
                self.requests += 1
                self._observe(url, e.headers)
                text = raw.decode("utf-8", "replace").strip()
                code = msg = None
                if text.startswith("{"):
                    try:
                        j = json.loads(text)
                        code, msg = j.get("code"), j.get("msg")
                    except Exception:
                        pass
                # 429 限频 / 418 封禁 / 5xx 可重试
                retriable = e.code in (429, 418, 500, 502, 503, 504)
                if not retriable:
                    raise BinanceAPIError(e.code, code, msg or text[:200], url) from None
                if not allow_retry or attempt > self.max_retries:
                    raise RetryExhausted(
                        f"HTTP {e.code} 重试 {self.max_retries} 次仍失败: {url}") from None
                ra = e.headers.get("Retry-After")
                if e.code in (429, 418):
                    delay = float(ra) if ra and ra.isdigit() else (30.0 if e.code == 429 else 120.0)
                else:
                    delay = min(60.0, 1.5 * (2 ** (attempt - 1))) + random.uniform(0, 0.6)
                if self.verbose:
                    log(f"[{e.code}] {path} -> 退避 {delay:.1f}s 后第 {attempt + 1} 次尝试"
                        + (f" (Retry-After={ra})" if ra else ""))
                time.sleep(delay)

            except (urllib.error.URLError, socket.timeout, TimeoutError,
                    ConnectionResetError, ssl.SSLError, json.JSONDecodeError) as e:
                if not allow_retry or attempt > self.max_retries:
                    raise RetryExhausted(f"网络/解析失败（重试 {self.max_retries} 次）: {url} :: {e}") from None
                delay = min(30.0, 1.2 * (2 ** (attempt - 1))) + random.uniform(0, 0.5)
                if self.verbose:
                    log(f"[ERR] {path} {type(e).__name__} -> 退避 {delay:.1f}s")
                time.sleep(delay)


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
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
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
