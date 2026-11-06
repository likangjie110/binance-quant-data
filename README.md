# 量化数据源 · 币安桌面端逆向分析

用 REA 对 Binance macOS 桌面端（2.6.0，Electron）做静态逆向，回答两个问题：

1. **币安的数据源来自哪里？**
2. **能不能我自己拉数据？**

## 先看结论

- 币安桌面端**不接第三方数据源**，行情/账户都走**币安自己的公网 API**：
  - 启动先拉动态配置（CloudFront 或 `www.binance.com`），拿到域名线路；
  - 再拉 `dynamic-domain` 拿到 WebSocket 主机；
  - 主进程把所有路径含 `api/` 的请求改写到 `apiHost`（默认 `www.binance.com`）。
- **行情可以自己拉，完全公开、不需要 API Key**：
  - REST：`api.binance.com/api/v3`（现货）、`fapi`（U 本位）、`dapi`（币本位）、`eapi`（期权）；
  - WebSocket：`stream.binance.com`、`fstream.binance.com` 的 `/market` 或 `/public`、`dstream.binance.com`、`ws-api`/`ws-fapi`；
  - 历史：`data.binance.vision`（日/月 zip + `.CHECKSUM`，已实测 sha256 通过）。
- **账户数据**要用你自己的 API Key；App 的 `/bapi/.../private/*` 是登录态内部接口，不要复用。
- **App 内部流**（`sfstream`/`sdstream`/`nbstream`）是私有 gzip/token 协议，外部接不了，也不需要。

## 交付物

| 文件 | 内容 |
|---|---|
| **`币安数据源分析报告.md`** | 主报告：启动链、数据源清单、公开/私有判定、实测证据、自取方案、坑 |
| `tools/binance_pull.py` | 纯标准库行情拉取器（spot/um/cm/option × klines/ticker24h/depth/exchangeinfo/symbols） |
| `work/rea/REA_EVIDENCE.md` | REA 证据台账（证据 ID、对象、结论、局限） |
| `work/evidence/` | 引导配置原始响应（明文 + JWT）、动态域名、限频表 |
| `work/evidence_anchors.json` | 打包产物字节级锚点（文件/行号/偏移/片段） |
| `work/verify/verify_report.md` | REST 端点验证报告（108 次探针、结构、踩坑） |
| `work/ws/ws_report.md` | WebSocket 实测报告（含合约路由迁移关键发现） |
| `work/ws/history_report.md` | data.binance.vision 路径规则与校验 |
| `work/sources.json` | 机器可读的数据源清单 |
| `用户数据流接入指南.md` | **私有实时推送**接入指南（API Key、事件类型、错误码） |
| `tools/binance_user_stream.py` | 用户数据流工具：`selftest` / `check` / `snapshot` / `listen`（只读） |
| `tools/event_sink.py` | 事件落库（JSONL/CSV/SQLite/PostgreSQL）+ 策略信号引擎示例 |
| `sql/binance_stream_schema.sql` | PostgreSQL 表结构（6 张表，含常用查询） |

## 快速开始

```bash
# 1) 拉现货 K 线
python3 tools/binance_pull.py klines --market spot --symbol BTCUSDT --interval 1h --limit 24

# 2) 拉 U 本位合约
python3 tools/binance_pull.py klines --market um --symbol BTCUSDT --interval 1h --limit 24

# 3) 历史数据（先校验再解压）
curl -O https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1h/BTCUSDT-1h-2026-11-05.zip
curl -O https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1h/BTCUSDT-1h-2026-11-05.zip.CHECKSUM
shasum -a 256 -c BTCUSDT-1h-2026-11-05.zip.CHECKSUM && unzip BTCUSDT-1h-2026-11-05.zip
```

## 私有实时推送（需要你自己的 API Key）

```bash
# 先无密钥自检
python3 tools/binance_user_stream.py selftest
# 配置 BINANCE_API_KEY / BINANCE_API_SECRET 后
python3 tools/binance_user_stream.py check
python3 tools/binance_user_stream.py snapshot --out work/private
python3 tools/binance_user_stream.py listen --markets spot,um --out work/private --duration 300
```

落库与信号（不需要 API Key 即可自检）：

```bash
python3 tools/event_sink.py selftest --out work/signals/selftest          # CSV/SQLite/信号
.venv/bin/python tools/event_sink.py selftest --out work/signals/selftest \
    --pg-dsn "postgresql://user:pass@127.0.0.1:5432/quant"                # 加 PostgreSQL
```

监听时落库：`--sink jsonl,csv,sqlite[,pg] --signals`。

详见 `用户数据流接入指南.md`。三条通道：现货走 WS API `userDataStream.subscribe.signature`（旧 listenKey 已 410）、
U 本位走 `/fapi/v1/listenKey` + `wss://fstream.binance.com/private/ws`、币本位走 `wss://dstream.binance.com/ws/<listenKey>`。

## 三个最容易踩的坑

1. **合约 WS 已迁移**：必须用 `wss://fstream.binance.com/market/ws/<stream>`（行情）或 `/public/ws/`（盘口）；
   旧 `/ws/` 会「握手成功但 0 帧」。
2. **`eapi` 期权 symbol 必须是未到期合约**（如 `BTC-261107-73000-C`），不是 `BTCUSDT`。
3. **历史数据格式**：spot 无表头、µs 时间戳；UM/CM 有表头、ms 时间戳。

## 复现 REA 分析

```bash
# 解包 asar（work/asar_extract 已生成；重做时把 asar 内文件与 app.asar.unpacked 合并）
rea analyze-javascript-application work/asar_extract --artifact-format directory \
    --source-path "dist/main-process/main.js" --format json > work/rea/main_process.json
rea analyze-javascript-application work/asar_extract --artifact-format directory \
    --source-path "resources/apps/trade-spot/static/main.68da5671.js" --format json > work/rea/trade_spot.json
python3 work/rea/extract_endpoints.py work/rea/trade_spot.json
```
