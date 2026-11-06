#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
binance_pull.py —— 币安公开行情 REST 拉取器（仅 Python 标准库，无第三方依赖）

面向币安 macOS 桌面端 2.6.0 实际使用的公开行情接口：
    spot   : https://api.binance.com/api/v3      （也可 --spot-host www 走桌面端默认 apiHost）
    um     : https://fapi.binance.com/fapi/v1    （U 本位永续/交割）
    cm     : https://dapi.binance.com/dapi/v1    （币本位永续/交割）
    option : https://eapi.binance.com/eapi/v1    （期权，symbol 必须是合约如 BTC-261107-73000-C）

全部端点均【无需 API key】。脚本实现：
  * 限频响应头读取（X-MBX-USED-WEIGHT-1M）+ 接近上限时自动让路
  * 429 / 418 / 5xx / 网络错误 指数退避重试，尊重 Retry-After
  * K 线按 startTime 游标分页，自动去重、跨市场 limit 上限自适应
  * CSV + JSON 元数据落盘（临时文件 + 原子替换）

用法示例：
    python3 tools/binance_pull.py klines --market spot --symbol BTCUSDT --interval 1h --limit 48
    python3 tools/binance_pull.py klines --market um --symbol BTCUSDT --interval 1h \
            --start 2026-10-01 --end 2026-10-08 --out work/verify/data
    python3 tools/binance_pull.py ticker24h --market spot --symbols BTCUSDT,ETHUSDT
    python3 tools/binance_pull.py symbols --market option --underlying BTCUSDT --expiring-days 7
    python3 tools/binance_pull.py klines --market option --symbol BTC-261107-73000-C --interval 1h
    python3 tools/binance_pull.py depth --market spot --symbol BTCUSDT --limit 20
    python3 tools/binance_pull.py exchangeinfo --market um --symbol BTCUSDT

退出码：0 成功；1 参数/接口错误；2 重试耗尽。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import socket
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# ----------------------------------------------------------------------------
# 常量：各市场主机 / 端点前缀 / K 线单次上限 / 官方权重上限（来自 exchangeInfo）
# ----------------------------------------------------------------------------
# wlimit 来源：各市场 GET {base}{prefix}/exchangeInfo 的 rateLimits[REQUEST_WEIGHT].limit
# 实测（2026-11-06 UTC）：spot 6000/min、um 2400/min、cm 2400/min、option 400/min
MARKETS = {
    "spot":   {"base": "https://api.binance.com",  "prefix": "/api/v3",  "kmax": 1000, "wlimit": 6000,
               "desc": "现货"},          # rateLimits: REQUEST_WEIGHT 6000/min
    "um":     {"base": "https://fapi.binance.com", "prefix": "/fapi/v1", "kmax": 1500, "wlimit": 2400,
               "desc": "U 本位合约"},     # rateLimits: REQUEST_WEIGHT 2400/min
    "cm":     {"base": "https://dapi.binance.com", "prefix": "/dapi/v1", "kmax": 1500, "wlimit": 2400,
               "desc": "币本位合约"},     # rateLimits: REQUEST_WEIGHT 2400/min
    # 期权：eapi exchangeInfo.rateLimits -> REQUEST_WEIGHT 400/min、ORDERS 100/min、ORDERS 30/10s
    "option": {"base": "https://eapi.binance.com", "prefix": "/eapi/v1", "kmax": 1500, "wlimit": 400,
               "desc": "期权"},
}
WWW_SPOT_BASE = "https://www.binance.com"   # 桌面端 prod 默认 apiHost

# 桌面端 UA（客户端身份影响 CDN 策略，实测各 UA 均可 200，但保持与桌面端一致更稳）
DEFAULT_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Binance/2.6.0 Chrome/120.0.0.0 Electron/28.0.0 Safari/537.36")

KLINE_HEADER = [
    "open_time_ms", "open_time_iso", "open", "high", "low", "close", "volume",
    "close_time_ms", "close_time_iso", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]
TICKER_FIELDS = [
    "symbol", "lastPrice", "priceChangePercent", "openPrice", "highPrice", "lowPrice",
    "volume", "quoteVolume", "weightedAvgPrice", "count", "openTime", "closeTime",
]

INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "6h": 21_600_000,
    "8h": 28_800_000, "12h": 43_200_000, "1d": 86_400_000, "3d": 259_200_000,
    "1w": 604_800_000, "1M": 2_592_000_000,
}


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

    def __init__(self, timeout=20, max_retries=5, proxy=None, user_agent=DEFAULT_UA,
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


def log(msg):
    print(msg, flush=True)


def now_iso_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ms_to_iso(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def parse_time(value):
    """支持 'YYYY-MM-DD'、'YYYY-MM-DD HH:MM'、ISO8601、纯毫秒。返回 epoch ms、UTC。"""
    if value is None:
        return None
    v = str(value).strip()
    if v.isdigit() and len(v) >= 12:
        return int(v)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(v, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        raise argparse.ArgumentTypeError(f"无法解析时间: {value!r}") from None


# ----------------------------------------------------------------------------
# 输出工具
# ----------------------------------------------------------------------------
def ensure_dir(path):
    if path and not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def atomic_write(path, write_fn, mode="w", **kw):
    d = os.path.dirname(os.path.abspath(path))
    ensure_dir(d)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_", suffix=".part")
    os.close(fd)
    try:
        with open(tmp, mode, **kw) as fh:
            write_fn(fh)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_json(path, obj):
    atomic_write(path, lambda fh: json.dump(obj, fh, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path, header, rows):
    def _w(fh):
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    atomic_write(path, _w, encoding="utf-8", newline="")


# ----------------------------------------------------------------------------
# 业务：K 线
# ----------------------------------------------------------------------------
def normalize_kline(row):
    """统一 12 列 K 线 -> CSV 行；缺列自动补空。"""
    cells = list(row) + [""] * max(0, 12 - len(row))
    cells = cells[:12]
    return [
        cells[0], ms_to_iso(cells[0]), cells[1], cells[2], cells[3], cells[4], cells[5],
        cells[6], ms_to_iso(cells[6]), cells[7], cells[8], cells[9], cells[10], cells[11],
    ]


def cmd_klines(args, client):
    mk = MARKETS[args.market]
    base = WWW_SPOT_BASE if (args.market == "spot" and args.spot_host == "www") else mk["base"]
    prefix = mk["prefix"]
    client.set_weight_limit(urllib.parse.urlsplit(base).netloc, mk["wlimit"])

    start = parse_time(args.start)
    end = parse_time(args.end)
    limit = args.limit
    if start is None and end is not None and limit is None:
        limit = mk["kmax"]
    if start is None and end is None:
        limit = limit or 500

    symbol = args.symbol
    if args.market == "option" and "-" not in symbol:
        raise SystemExit(
            f"eapi 期权 symbol 必须是合约代码（形如 BTC-261107-73000-C），收到 {symbol!r}。\n"
            f"先用 `python3 tools/binance_pull.py symbols --market option --underlying BTCUSDT` 取合法合约。")

    rows, seen, reqs = [], set(), 0
    cursor = start
    # 单页模式（未给 --start）：只取最近 limit 条，页大小=limit；
    # 分页模式（给了 --start）：每页压满市场上限，用 startTime 游标翻页。
    page_cap = min(limit or 500, mk["kmax"]) if start is None else mk["kmax"]
    max_rows = args.max_rows if args.limit is None else min(args.max_rows, args.limit)
    t_start = time.time()

    while True:
        params = {"symbol": symbol, "interval": args.interval, "limit": page_cap}
        if cursor is not None:
            params["startTime"] = cursor
        if end is not None:
            params["endTime"] = end
        batch, meta = client.get(base, prefix + "/klines", params)
        reqs += 1
        if not isinstance(batch, list):
            raise BinanceAPIError(meta["status"], None, f"返回非列表: {str(batch)[:120]}", meta["url"])
        new = 0
        for item in batch:
            key = item[0]
            if key in seen:
                continue
            seen.add(key)
            rows.append(normalize_kline(item))
            new += 1
        if not args.quiet:
            log(f"    -> 本页 {len(batch)} 条，新增 {new}，累计 {len(rows)}")
        if not batch or new == 0:
            break
        if max_rows and len(rows) >= max_rows:
            rows = rows[:max_rows]
            break
        if cursor is None:          # 只取最近 N 条，单页即可
            break
        if len(batch) < page_cap:   # 已到尾部
            break
        cursor = int(batch[-1][0]) + 1   # +1ms 避免重复，startTime 为闭区间
        if end is not None and cursor > end:
            break

    outdir = os.path.join(args.out, args.market, symbol.replace("/", "_"))
    ensure_dir(outdir)
    base_name = f"{args.interval}_klines"
    csv_path = os.path.join(outdir, base_name + ".csv")
    write_csv(csv_path, KLINE_HEADER, rows)
    meta = {
        "generated_at": now_iso_utc(),
        "market": args.market,
        "market_desc": mk["desc"],
        "host": base,
        "endpoint": prefix + "/klines",
        "symbol": symbol,
        "interval": args.interval,
        "row_count": len(rows),
        "first_open_time": ms_to_iso(rows[0][0]) if rows else None,
        "last_open_time": ms_to_iso(rows[-1][0]) if rows else None,
        "requests": reqs,
        "elapsed_s": round(time.time() - t_start, 2),
        "used_weight_1m_last": client.last_weight.get(urllib.parse.urlsplit(base).netloc),
        "limit_headers_last": client.last_headers.get(urllib.parse.urlsplit(base).netloc),
        "auth_required": False,
        "csv": os.path.abspath(csv_path),
    }
    write_json(os.path.join(outdir, base_name + ".meta.json"), meta)
    if not rows and args.market == "option":
        log("  ! eapi 期权 K 线只返回窗口内【有成交】的 K 线；该合约可能极不活跃。"
            "\n    换更活跃/更近月的合约试试："
            "python3 tools/binance_pull.py symbols --market option --underlying BTCUSDT")
    log(f"\n✔ {mk['desc']} {symbol} {args.interval}: {len(rows)} 根 K 线"
        f"（{meta['first_open_time']} → {meta['last_open_time']}），{reqs} 次请求，"
        f"{meta['elapsed_s']}s\n  CSV : {csv_path}\n  META: {csv_path[:-4]}.meta.json")
    return 0


# ----------------------------------------------------------------------------
# 业务：24h ticker
# ----------------------------------------------------------------------------
def cmd_ticker24h(args, client):
    mk = MARKETS[args.market]
    base = WWW_SPOT_BASE if (args.market == "spot" and args.spot_host == "www") else mk["base"]
    client.set_weight_limit(urllib.parse.urlsplit(base).netloc, mk["wlimit"])
    symbols = [s.strip().upper() for s in (args.symbols or "").split(",") if s.strip()]

    if symbols:
        data = []
        for s in symbols:
            obj, _ = client.get(base, mk["prefix"] + "/ticker/24hr", {"symbol": s})
            data.append(obj)
    else:
        log("  未指定 --symbols，拉取全市场 ticker/24hr（权重较高，现货=80）")
        obj, _ = client.get(base, mk["prefix"] + "/ticker/24hr")
        data = obj if isinstance(obj, list) else [obj]

    outdir = os.path.join(args.out, args.market, "_ticker24h")
    ensure_dir(outdir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = os.path.join(outdir, f"ticker24hr_{stamp}.json")
    csv_path = os.path.join(outdir, f"ticker24hr_{stamp}.csv")
    write_json(json_path, data)
    rows = [[d.get(k) for k in TICKER_FIELDS] for d in data if isinstance(d, dict)]
    write_csv(csv_path, TICKER_FIELDS, rows)
    log(f"\n✔ {mk['desc']} 24h ticker: {len(rows)} 个交易对\n  JSON: {json_path}\n  CSV : {csv_path}")
    return 0


# ----------------------------------------------------------------------------
# 业务：深度
# ----------------------------------------------------------------------------
def cmd_depth(args, client):
    mk = MARKETS[args.market]
    base = WWW_SPOT_BASE if (args.market == "spot" and args.spot_host == "www") else mk["base"]
    client.set_weight_limit(urllib.parse.urlsplit(base).netloc, mk["wlimit"])
    obj, meta = client.get(base, mk["prefix"] + "/depth", {"symbol": args.symbol, "limit": args.limit})
    outdir = os.path.join(args.out, args.market, args.symbol.replace("/", "_"))
    ensure_dir(outdir)
    path = os.path.join(outdir, f"depth_{args.limit}.json")
    payload = {"generated_at": now_iso_utc(), "host": base, "symbol": args.symbol,
               "lastUpdateId": obj.get("lastUpdateId"), "bids": obj.get("bids", [])[:50],
               "asks": obj.get("asks", [])[:50],
               "total_bids": len(obj.get("bids", [])), "total_asks": len(obj.get("asks", []))}
    write_json(path, payload)
    log(f"\n✔ depth {args.symbol}: bids={payload['total_bids']} asks={payload['total_asks']}"
        f" lastUpdateId={payload['lastUpdateId']}\n  JSON: {path}")
    return 0


# ----------------------------------------------------------------------------
# 业务：exchangeInfo
# ----------------------------------------------------------------------------
def cmd_exchangeinfo(args, client):
    mk = MARKETS[args.market]
    base = WWW_SPOT_BASE if (args.market == "spot" and args.spot_host == "www") else mk["base"]
    client.set_weight_limit(urllib.parse.urlsplit(base).netloc, mk["wlimit"])
    if args.symbol is None and args.market == "spot":
        log("  ! 现货全量 exchangeInfo 约 17.8MB（3742 个交易对，实测），建议加 --symbol 只取单对")
    obj, meta = client.get(base, mk["prefix"] + "/exchangeInfo", {"symbol": args.symbol})
    outdir = os.path.join(args.out, args.market, "_exchangeinfo")
    ensure_dir(outdir)
    tag = args.symbol or "ALL"
    path = os.path.join(outdir, f"exchangeInfo_{tag}.json")
    write_json(path, obj)
    rl = obj.get("rateLimits", [])
    log(f"\n✔ exchangeInfo {args.market} {tag}: symbols={len(obj.get('symbols', []))}"
        f" rateLimits={json.dumps(rl, ensure_ascii=False)}\n  JSON: {path}")
    return 0


# ----------------------------------------------------------------------------
# 业务：列出合法期权合约（eapi 特有坑）
# ----------------------------------------------------------------------------
def cmd_symbols(args, client):
    base = MARKETS["option"]["base"] if args.market == "option" else MARKETS[args.market]["base"]
    prefix = MARKETS[args.market]["prefix"]
    client.set_weight_limit(urllib.parse.urlsplit(base).netloc, MARKETS[args.market]["wlimit"])
    obj, _ = client.get(base, prefix + "/exchangeInfo")
    now_ms = time.time() * 1000
    if args.market == "option":
        items = []
        for s in obj.get("optionSymbols", []):
            if args.underlying and s.get("underlying") != args.underlying.upper():
                continue
            exp = float(s.get("expiryDate", 0))
            if exp <= now_ms:
                continue
            days = (exp - now_ms) / 86400000
            if args.expiring_days and days > args.expiring_days:
                continue
            items.append({"symbol": s["symbol"], "underlying": s.get("underlying"),
                          "side": s.get("side"), "strike": s.get("strikePrice"),
                          "expiry_utc": ms_to_iso(exp), "days_left": round(days, 2)})
        items.sort(key=lambda x: (x["underlying"] or "", x["expiry_utc"], x["strike"] or ""))
        if args.json:
            print(json.dumps(items, ensure_ascii=False, indent=2))
        else:
            log(f"共 {len(items)} 个可交易期权合约（当前时间 {now_iso_utc()}）")
            log(f"{'SYMBOL':<26}{'UNDERLYING':<12}{'SIDE':<6}{'STRIKE':<12}{'EXPIRY(UTC)':<22}DAYS")
            for it in items[: args.max_list]:
                log(f"{it['symbol']:<26}{it['underlying']:<12}{it['side']:<6}"
                    f"{it['strike']:<12}{it['expiry_utc']:<22}{it['days_left']}")
            if len(items) > args.max_list:
                log(f"... 省略 {len(items) - args.max_list} 条（用 --max-list 调整）")
        return 0

    syms = [s["symbol"] for s in obj.get("symbols", []) if s.get("status") == "TRADING"]
    if args.json:
        print(json.dumps(syms, ensure_ascii=False, indent=2))
    else:
        log(f"{MARKETS[args.market]['desc']} TRADING 交易对 {len(syms)} 个：")
        for i in range(0, min(len(syms), args.max_list), 8):
            log("  " + "  ".join(f"{x:<14}" for x in syms[i:i + 8]))
    return 0


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def _global_opts(p, child=False):
    """全局选项；child=True 时挂到子命令下，允许写在子命令之后（默认值 SUPPRESS 不覆盖父级）。"""
    sup = argparse.SUPPRESS
    p.add_argument("--out", default=sup if child else "data/binance",
                   help="输出根目录（默认 data/binance）")
    p.add_argument("--proxy", default=sup if child else None,
                   help="可选 HTTP(S) 代理，如 http://127.0.0.1:7890")
    p.add_argument("--timeout", type=float, default=sup if child else 20.0,
                   help="单请求超时秒（默认 20）")
    p.add_argument("--max-retries", type=int, default=sup if child else 5,
                   help="可重试错误的最大重试次数")
    p.add_argument("--min-interval", type=float, default=sup if child else 0.12,
                   help="请求最小间隔秒，防突发")
    p.add_argument("--quiet", action="store_true", default=sup if child else False,
                   help="安静模式：不打印每请求日志")


def build_parser():
    p = argparse.ArgumentParser(
        prog="binance_pull.py",
        description="币安公开行情 REST 拉取器（桌面端 2.6.0 同源接口，无需 API key）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    _global_opts(p)
    sub = p.add_subparsers(dest="cmd", required=True)

    for name, help_text in (("klines", "拉取 K 线 → CSV + meta.json"),
                            ("ticker24h", "拉取 24h ticker → JSON + CSV")):
        s = sub.add_parser(name, help=help_text)
        _global_opts(s, child=True)
        s.add_argument("--market", required=True, choices=list(MARKETS), help="市场")
        s.add_argument("--spot-host", default="api", choices=["api", "www"],
                       help="现货主机：api=api.binance.com（默认），www=www.binance.com（桌面端 apiHost）")
        if name == "klines":
            s.add_argument("--symbol", required=True, help="交易对/合约，如 BTCUSDT / BTCUSD_PERP / BTC-261107-73000-C")
            s.add_argument("--interval", default="1h", help="周期：1m/5m/15m/1h/4h/1d/1w/1M 等")
            s.add_argument("--limit", type=int, default=None, help="单次/最近条数上限")
            s.add_argument("--start", default=None, help="起始时间（YYYY-MM-DD 或 epoch ms），指定后自动分页")
            s.add_argument("--end", default=None, help="结束时间")
            s.add_argument("--max-rows", type=int, default=20000, help="分页总行数保险阈值")
        else:
            s.add_argument("--symbols", default=None, help="逗号分隔的交易对；省略则全市场")

    s = sub.add_parser("depth", help="拉取盘口快照")
    _global_opts(s, child=True)
    s.add_argument("--market", required=True, choices=list(MARKETS))
    s.add_argument("--spot-host", default="api", choices=["api", "www"])
    s.add_argument("--symbol", required=True)
    s.add_argument("--limit", type=int, default=20, help="档位：现货 5/10/20/50/100/500/1000/5000；期权仅 10/20/50/100/1000")

    s = sub.add_parser("exchangeinfo", help="打印/保存交易规则与官方限频表")
    _global_opts(s, child=True)
    s.add_argument("--market", required=True, choices=list(MARKETS))
    s.add_argument("--spot-host", default="api", choices=["api", "www"])
    s.add_argument("--symbol", default=None)

    s = sub.add_parser("symbols", help="列出合法交易对（期权合约按到期日排序）")
    _global_opts(s, child=True)
    s.add_argument("--market", default="option", choices=list(MARKETS))
    s.add_argument("--underlying", default=None, help="期权标的，如 BTCUSDT")
    s.add_argument("--expiring-days", type=float, default=None, help="只看 N 天内到期的期权")
    s.add_argument("--max-list", type=int, default=40, help="最多显示条数")
    s.add_argument("--json", action="store_true", help="输出 JSON")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    client = BinanceClient(timeout=args.timeout, max_retries=args.max_retries,
                           proxy=args.proxy, min_interval=args.min_interval,
                           verbose=not args.quiet)
    if not args.quiet:
        log(f"binance_pull.py @ {now_iso_utc()} | 纯公开接口，无 API key")
    try:
        if args.cmd == "klines":
            return cmd_klines(args, client)
        if args.cmd == "ticker24h":
            return cmd_ticker24h(args, client)
        if args.cmd == "depth":
            return cmd_depth(args, client)
        if args.cmd == "exchangeinfo":
            return cmd_exchangeinfo(args, client)
        if args.cmd == "symbols":
            return cmd_symbols(args, client)
    except BinanceAPIError as e:
        log(f"\n✘ 接口错误: {e}")
        return 1
    except RetryExhausted as e:
        log(f"\n✘ 重试耗尽: {e}")
        return 2
    except KeyboardInterrupt:
        log("\n已中断")
        return 130
    return 1


if __name__ == "__main__":
    sys.exit(main())
