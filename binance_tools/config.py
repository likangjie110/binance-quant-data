"""运行常量：主机、端点、限频、UA（单一事实源，批次 2 收敛）。"""
from __future__ import annotations

# 桌面端 UA（客户端身份影响 CDN 策略；实测各 UA 均可 200，保持与桌面端一致更稳）
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Binance/2.6.0 Chrome/120.0.0.0 Electron/28.0.0 Safari/537.36")

# 公开行情：各市场主机 / 端点前缀 / K 线单次上限 / 官方权重上限（来自 exchangeInfo）
# wlimit 来源：各市场 GET {base}{prefix}/exchangeInfo 的 rateLimits[REQUEST_WEIGHT].limit
# 实测（2026-11-06 UTC）：spot 6000/min、um 2400/min、cm 2400/min、option 400/min
MARKETS = {
    "spot":   {"base": "https://api.binance.com",  "prefix": "/api/v3",  "kmax": 1000, "wlimit": 6000,
               "desc": "现货"},
    "um":     {"base": "https://fapi.binance.com", "prefix": "/fapi/v1", "kmax": 1500, "wlimit": 2400,
               "desc": "U 本位合约"},
    "cm":     {"base": "https://dapi.binance.com", "prefix": "/dapi/v1", "kmax": 1500, "wlimit": 2400,
               "desc": "币本位合约"},
    "option": {"base": "https://eapi.binance.com", "prefix": "/eapi/v1", "kmax": 1500, "wlimit": 400,
               "desc": "期权"},
}
WWW_SPOT_BASE = "https://www.binance.com"   # 桌面端 prod 默认 apiHost

# 私有接口 / 流
SPOT_REST = "https://api.binance.com"
UM_REST = "https://fapi.binance.com"
CM_REST = "https://dapi.binance.com"
SPOT_WS_API = "wss://ws-api.binance.com:443/ws-api/v3"
UM_PRIVATE_WS = "wss://fstream.binance.com/private/ws"
CM_PRIVATE_WS = "wss://dstream.binance.com/ws"
SPOT_PUBLIC_WS = "wss://stream.binance.com:9443"
UM_MARKET_WS = "wss://fstream.binance.com/market/ws"

KEEPALIVE_SPOT_SEC = 30 * 60   # 现货 WS API 订阅随连接存在
KEEPALIVE_FUT_SEC = 30 * 60    # listenKey 官方 60 分钟过期，30 分钟 PUT 一次
