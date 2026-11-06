# 可靠性说明

> 本文件描述"哪里会坏、怎么发现、怎么恢复"。所有条目都对应真实观测或已登记技术债。

## 1. 可靠性目标（当前为手工目标，非 SLA）

| 目标 | 当前状态 | 达标条件 |
|---|---|---|
| 私有事件不丢 | 未保证 | 落库成功后才继续消费；断线重连按 listenKey 补拉（事件无回放能力，需接受窗口丢失） |
| 静默流可发现 | 未实现 | 180s 无消息触发重连（TD-REL-001，批次 1） |
| 鉴权错误快速失败 | 已实现 | 连续 2 次 -2014/-2015 停止该市场并给出提示 |
| 限频不越界 | 已实现（REST） | 读 `X-MBX-USED-WEIGHT-1M`，≥85% 休眠 4s、≥95% 休眠 25s |
| 写库幂等 | 已实现 | orders upsert、fills 去重、events 追加 |
| 多市场写库可用 | **不可用（P0）** | 单写线程改造 + 并发回归（TD-RUNTIME-001） |

## 2. 失败模式与响应

| 症状 | 根因 | 检测 | 响应 |
|---|---|---|---|
| 合约 WS 握手 101 但 0 帧 | 旧路由只推 `/public` 数据（ADR-003） | 消息计数 | 改用 `/market`/`/public`；设置静默看门狗 |
| `nbstream/sfstream` 1006/302 | App 内部私有通道（token+gzip） | 连接错误码 | 不要用；公开流替代 |
| listenKey `-1125` / 过期 | 超过 60 分钟未续期 | 事件 `listenKeyExpired` | 自动重建（已实现）；30 分钟 PUT 续期 |
| 现货订阅 401/-2015 | Key 权限/IP 白名单/Key 失效 | 订阅响应 | 连续 2 次即停并提示检查权限 |
| `-1022` 签名错误 | secret 错或参数顺序被动 | 响应 | 重新生成 Key；不要手改签名参数 |
| 429 / 418 | 权重超限 / IP 被封 | 状态码 + `Retry-After` | 429 按 Retry-After（默认 30s）；418 退避 120s |
| TLS `UNEXPECTED_EOF` / `SSL_ERROR_SYSCALL` | 代理链路抖动 | 异常类型 | 指数退避重试（脚本已内置） |
| SQLite `ProgrammingError: … same thread` | 跨线程共享连接（P0） | 异常 | **当前无解**；批次 1 修复前不要多市场写 SQLite/PG |
| PG 写入慢/卡 | 每事件 commit（TD-PERF-001） | 写入延迟 | 批量提交（批次 5） |
| eapi 400 / 空 K 线 | 合约过期 / 无成交 | 响应 | 先取 `optionSymbols` 过滤 `expiryDate`；容忍空数组 |

## 3. 重试与退避策略（现状）

| 场景 | 策略 | 位置 |
|---|---|---|
| REST 5xx | 指数退避 ×2^n + 抖动，上限 8s（pull 最长 60s） | `binance_pull.py` / `binance_user_stream.py` |
| REST 网络/TLS | 同上，重试 3~5 次 | 同上 |
| 429 | 读 `Retry-After`，缺省 30s | `binance_pull.py` |
| 418 | 120s | `binance_pull.py` |
| WS 重连 | 指数退避，上限 30s；listenKey 复用/重建 | `binance_user_stream.py` |
| 鉴权失败 | 不重试，连续 2 次熔断 | `binance_user_stream.py` |

## 4. 运行手册（Runbook）

### 4.1 私有流无数据

1. `python3 tools/binance_user_stream.py check` → 区分网络 / 权限 / 签名。
2. 用 `selftest` 排除 WS 客户端问题（无密钥也可跑）。
3. 核对路由：现货 `ws-api/v3`；合约 `/private/ws?listenKey=`；币本位 `dstream/ws/`。
4. 仍无数据：抓 60s 日志，确认是否有 ping/pong（有连接无业务事件 vs 连接断开）。

### 4.2 落库失败

1. SQLite：确认是否多市场并发（P0 已知）→ 先单市场。
2. PG：确认 `psycopg` 在运行环境（`.venv/bin/python`），DSN 权限、库是否存在。
3. 检查磁盘空间与文件权限（`work/private/`、`work/signals/`）。

### 4.3 数据对不上

- 已收盘 K 线以 REST 为准；`www.binance.com` 与 `api.binance.com` 已收盘数据一致（开放那根可能不同）。
- 历史 zip 与 REST 的差异：spot 历史时间戳为**微秒**，REST 为毫秒（`docs/TROUBLESHOOTING.md`）。
- 原始事件永远保留在 `stream_events.raw`，派生表可重建。

## 5. 待补的可靠性能力（批次 1/5）

- [ ] 静默流看门狗（`--idle-timeout`，默认 180s）
- [ ] 优雅关闭（`threading.Event` + WS/sink 清理，Ctrl-C 5s 内退出）
- [ ] 单写线程 + 有界队列（背压策略：满队列丢弃并计数，或阻塞监听线程）
- [ ] 写入批量提交（N 条 / ≤1s）
- [ ] 结构化日志与指标（事件速率、重连次数、落库失败数）
