# 故障排查

> 先看症状，再看根因与动作。涉及账户的错误码，优先检查 API Key 权限与 IP 白名单。

## 1. 鉴权类

| 症状 | 根因 | 动作 |
|---|---|---|
| HTTP 401 `-2014 API-key format invalid` | Key 字符/长度不对、复制带空格、Key 已删除 | 重新复制完整 Key；确认 `^[a-zA-Z0-9]{36,64}$` |
| HTTP 401 `-2015 Invalid API-key, IP, or permissions` | IP 不在白名单 / 权限没勾"允许读取" / 现货与合约权限分开 | 账户 → API 管理：补 IP、勾读权限；`check` 会再验证 |
| HTTP 401 `-1022 Signature for this request is not valid` | secret 错、参数被改、系统时间偏差大 | 重新生成 Key；校准系统时间；不要手改签名参数 |
| WS 订阅返回 `status:401` + `-2015` | 同上（WS API 也走 Key 校验） | 先修 REST Key，再试 |
| `-1100 Illegal characters found in parameter 'apiKey'` | Key 含非法字符（引号/空格/换行） | 检查复制来源；用 `--key-file` 避免 shell 转义 |

## 2. 私有流类

| 症状 | 根因 | 动作 |
|---|---|---|
| 合约 WS 握手 101 但 0 帧 | 用了旧路径 `/ws/<stream>`，旧路径只推 `/public` 数据（ADR-003）；另一可能是真的无事件 | 行情改 `/market/ws`，盘口改 `/public/ws`；看门狗 180s 无消息会自动重连 |
| `wss://nbstream.binance.com` 1006/404 | App 内部边缘流（token+gzip），非公开标准流 | 不要用；公开流替代 |
| `sfstream/sdstream` 302 → `www.binance.com/en` | 同上，App 私有 gzip 通道 | 不要用 |
| 现货订阅成功但长时间无事件 | 账户无委托/成交（事件驱动） | 下测试单或等待；用 `check` 确认订阅成功 |
| `listenKeyExpired` 事件 | listenKey 超过 60 分钟 | 脚本自动重建；确认 30 分钟 PUT 续期未被网络中断 |
| `-1125 This listenKey does not exist` | listenKey 过期/被删 | 重新 POST 创建；不要复用旧 key |
| ~~多市场 + `--sink sqlite/pg` 崩溃~~ | 跨线程共享 DB 连接（TD-RUNTIME-001，**批次 1 已修**） | 已改为单写线程；若复现，确认没有绕过 `StreamWriter` |
| 鉴权失败反复重连 | 脚本熔断阈值 | 连续 2 次 -2014/-2015 会停止该市场；检查 Key 后重跑 |

## 3. REST / 限频类

| 症状 | 根因 | 动作 |
|---|---|---|
| HTTP 429 `Too Many Requests` | 权重超限 | 读 `Retry-After` 退避（脚本已处理）；降低频率 |
| HTTP 418 `I'm a teapot` | IP 被临时封禁 | 退避 ≥120s；检查代理出口是否共享 |
| 请求偶发 TLS `UNEXPECTED_EOF` / `SSL_ERROR_SYSCALL` | 代理链路抖动 | 重试即可（脚本内置）；换稳定出口 |
| `X-MBX-USED-WEIGHT-1M` 数值乱跳 | 代理出口 IP 轮换，权重桶不同 | 生产固定出口 IP |
| 期权 `-1121 symbol ... does not exist` | 用了现货符号或已过期合约 | 先 `/eapi/v1/exchangeInfo` 取合法 `optionSymbols[]` |
| 期权 `-4021 Invalid depth limit` | depth 档位只允许 10/20/50/100/1000 | 换合法档位 |
| fapi `404` HTML 页面 | 端点不存在（如 `/fapi/v1/markPrice`） | 标记价格用 `/fapi/v1/premiumIndex` |
| 现货 `POST /api/v3/userDataStream` 410 | 旧 listenKey 端点已下线 | 用 WS API `userDataStream.subscribe.signature` |
| 全量 `exchangeInfo` 巨大/超时 | spot 全量约 17.8MB | 用 `?symbol=` 单对查询 |

## 4. 数据格式类

| 症状 | 根因 | 动作 |
|---|---|---|
| 历史 zip 时间戳是 16 位 | spot 自 2025-01-01 起用**微秒**；UM/CM 用毫秒 | 解析时按市场区分（`docs/generated/db-schema.md` 无此字段，见指南） |
| spot 历史 CSV 无表头 | spot 日/月文件无表头；UM 有表头 | 读取时按市场决定是否 `header=None` |
| 已收盘 K 线两根接口不一致 | 一条是"当前未收盘"那根 | 只比较已收盘；或按 openTime 对齐 |
| `www.binance.com` 与 `api.binance.com` 数据不同 | 同一数据源的开放 K 线时间差 | 用已收盘数据；不要混用抓取时刻 |
| 期权 K 线返回 `[]` | 该合约无成交 | 换活跃合约；不要把空数组当错误 |
| dapi/eapi ticker 是数组 | 与 spot/fapi 返回形态不同 | 解析兼容两种形态 |

## 5. 落库与信号类

| 症状 | 根因 | 动作 |
|---|---|---|
| `ProgrammingError: SQLite objects created in a thread…` | 绕过 `StreamWriter` 直连 DB（批次 1 后不应出现） | 检查调用路径；所有写入必须经 `StreamWriter.write` |
| PG `ModuleNotFoundError: psycopg` | 用了系统 Python 而非 `.venv` | `.venv/bin/python ...`；或安装 `psycopg[binary]` |
| PG `password authentication failed` | DSN 错误 | 检查用户名/密码/库名；改用环境变量（TD-SEC-001 待修） |
| 重复写入导致 orders 重复 | 主键冲突未处理 | 正常行为是 upsert；若重复说明 market/order_id 不一致 |
| 信号持仓与交易所有偏差 | 现货持仓由成交推算；合约以 ACCOUNT_UPDATE 为准 | 以交易所快照为准；核对 `positions` 表最近一条 |
| CSV 文件被占用 | 其他程序打开（Excel） | 关闭后重跑；脚本 append 模式 |

## 6. 网络与环境

| 现象 | 说明 |
|---|---|
| `remote_ip` 为 `198.18.x.x` | Clash/TUN 的 fake-IP 段，正常；不代表真实出口 |
| 出口 IP 每次不同 | 多出口代理；会影响限频桶与 IP 白名单 |
| 中国大陆直连币安域名失败 | 需可用线路/代理；同时确认当地法规与服务条款 |
| `.venv` 被 uv 托管 Python 拒绝 | 系统 Python 受 PEP 668 管理，必须用独立 venv |
| `git` 报 `missing config key GIT_CONFIG_KEY_0` | 环境注入了不完整的 `GIT_CONFIG_*`；运行时 `env -u GIT_CONFIG_COUNT … git …` |

## 7. 诊断命令速查

```bash
python3 tools/binance_user_stream.py selftest          # WS/签名底座
python3 tools/binance_user_stream.py check --markets spot,um,cm
python3 tools/event_sink.py selftest --out /tmp/sink   # 落库链路
python3 scripts/analysis/scan_project.py --out /tmp/scan
python3 scripts/docs/check_docs.py
python3 scripts/analysis/repro_thread_safety.py; echo "exit=$?"
```
