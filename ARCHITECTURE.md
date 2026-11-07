# 架构总览

> 本文件回答"系统由哪些部分构成、依赖往哪个方向流、改哪里会伤到哪里"。
> 不描述每个函数做什么（那是代码的事）；描述**边界、不变量与失败模式**。

## 1. 领域地图

| 领域 | 职责 | 当前实现 | 对外产物 |
|---|---|---|---|
| 数据源逆向 | 用 REA 确认桌面端数据来源与协议边界 | 离线分析（证据在 `work/`，报告在根目录） | `币安数据源分析报告.md` |
| 公开行情 | 现货/合约/期权的 REST 历史与快照拉取 | `tools/binance_pull.py` | CSV + meta.json |
| 私有实时推送 | 官方 API Key 的用户数据流（订单/成交/余额/持仓） | `tools/binance_user_stream.py` | JSONL/CSV/SQLite/PG 事件 |
| 事件处理 | 事件归一化、落库、策略信号 | `tools/event_sink.py` | 6 张表 + `signals_*.jsonl` |
| 工程治理 | 扫描、文档校验、改造计划 | `scripts/`、`docs/` | 计划/台账/质量评分 |

## 2. 当前代码结构与依赖方向（批次 2 包化后）

```
binance_tools/
├── cli.py        统一入口：按子命令分发；console_scripts: binance-tools
├── public.py     公开行情：klines / ticker24h / depth / exchangeinfo / symbols
├── private.py    私有推送：selftest / check / snapshot / listen（含 StreamWriter 单写线程）
├── event_cli.py  落库/信号 CLI：selftest / replay
├── client.py     BinanceClient（公开 GET：限频/退避/权重）+ http_json（私有签名请求）
├── ws.py         最小 RFC6455 客户端
├── signing.py    sign_payload / sign_rest / sign_ws
├── config.py     主机 / 端点 / UA / 限频常量（唯一事实源）
├── common.py     时间 / 掩码 / 数值 / 日志
├── normalize.py  事件归一化（唯一读裸交易所字段处）
├── fixtures.py   演示样例事件（selftest 与单测共享）
├── sinks.py      JSONL / CSV / SQLite / PG + build_sinks
├── signals.py    SignalEngine + SignalSink
└── __main__.py   支持 python3 -m binance_tools
tools/*.py        三个兼容薄壳（旧命令仍可用，仅转发到 binance_tools.cli）
```

### 依赖方向规则（可机械核对）

1. **单向**：`cli → public/private/event_cli → client/ws/sinks/signals/normalize → common/config/stdlib`；反向禁止。
2. **禁止跨 CLI 模块导入**：`public.py` 不得 import `private.py`，反之亦然；共享能力只能落到
   `client / ws / signing / sinks / normalize / common / config`。
3. **签名只在 `signing.py`**：REST 与 WS API 分别用 `sign_rest` / `sign_ws`，其他模块不得自行拼签名。
4. **DB 连接只在 `sinks.py`，且只在 writer 线程**：`SqliteBackend.connect` / `PgBackend.connect`（lazy 导入 psycopg）；
   监听线程只入队（`private.StreamWriter.write`）。
5. **原始交易所字段只在 `normalize.py` 解析**；sinks/信号只消费归一化结构。
6. **只读不变量**：全仓库不存在下单/撤单/提币调用；私有 Key 仅用于查询与订阅。

### 与代码的抽样核对（阶段 2/批次 2 验收）

| 规则 | 代码证据 | 结论 |
|---|---|---|
| 跨命令复用走共享模块 | `binance_tools/private.py:61-72`（导入 client/common/config/normalize/signing/sinks/ws） | 一致 |
| 可选依赖边界清晰 | `binance_tools/sinks.py:199` `PgBackend`；`:211` 内 `import psycopg`（lazy） | 一致 |
| 公开拉取依赖统一客户端 | `binance_tools/public.py:39-41`（导入 client/config/common，无 urllib 直连） | 一致 |
| DB 只在 sink | `binance_tools/sinks.py:135`（SQLite）、`:199`（PG）、`:221` `SqlSink` | 一致 |
| 旧入口仅为薄壳 | `tools/binance_pull.py` / `binance_user_stream.py` / `event_sink.py` 只 `from binance_tools.cli import ...` | 一致 |

## 3. 入口与兼容策略

| 方式 | 命令 | 说明 |
|---|---|---|
| 统一入口（安装后） | `binance-tools <命令>` | `pip install -e .` 提供 console_scripts（批次 2） |
| 无需安装 | `python3 -m binance_tools <命令>` | 仓库根目录直接运行 |
| 旧脚本兼容 | `python3 tools/binance_pull.py ...` 等 | 薄壳转发，参数/输出保持不变；下一版本可移除 |

统一命令集：`klines | ticker24h | depth | exchangeinfo | symbols | selftest | check | snapshot | listen | replay | sink-selftest`。

## 4. 关键数据流

### 4.1 公开行情（`binance_pull.py`）

```
参数(市场/交易对/周期) → 限频预算 → GET /api/v3|fapi|dapi|eapi → 解析 12 列
  → 分页游标(startTime) → CSV + meta.json（原子替换）
```
失败模式：429/418（退避）、5xx（指数退避）、TLS 抖动（重试）、eapi 合约过期（400，需先取合法合约）。

### 4.2 私有实时（`binance_user_stream.py`）

```
现货: WS API(ticker…, userDataStream.subscribe.signature)   ┐
U 本位: listenKey → /private/ws?listenKey=…                ├→ 事件 JSON → normalize()
币本位: listenKey → dstream /ws/<listenKey>                ┘        │
                                                                    ├→ CSV/JSONL/SQLite/PG
                                                                    └→ SignalEngine → signals_*.jsonl
```
失败模式：listenKey 过期、静默流（0 帧，看门狗 180s）、TLS 中断、鉴权失败（-2014/-2015/-1022）。
写入侧由单写线程 + 有界队列隔离（批次 1 修复 P0），队列满丢弃并计数。

### 4.3 落库（`event_sink.py`）

`normalize()` 统一三种市场字段 → sinks（幂等：orders upsert、fills 去重、events 追加）→ 信号状态机。

## 5. 不变量与失败边界

| 不变量 | 违反后果 | 强制手段 |
|---|---|---|
| 只读、无交易调用 | 安全与合规风险 | 代码评审 + 后续 CI 关键字扫描 |
| 核心仅标准库 | 部署/可移植性退化 | `pyproject` 依赖检查 + 评审 |
| 单写线程持有 DB 连接 | 崩溃/数据竞争 | `StreamWriter` 线程模型 + 并发回归测试（批次 1 已落地） |
| 原始字段只在 normalize 解析 | 各处兼容逻辑扩散 | 结构测试（批次 3） |
| 文档与代码同提交 | 文档腐烂、误导后续 agent | `check_docs.py` + PR 门禁 |

## 6. 已知架构债（详见 tech-debt-tracker）

- TD-ARCH-001/002/003：HTTP 客户端重复、`sys.path` 导入、无包元数据（批次 2）
- TD-DUP-001/002：两套 fan-out、DDL 双份（批次 2/5）
- TD-PERF-001：每事件 commit/print（批次 5）
- 已修复：TD-RUNTIME-001/002、TD-REL-001/002、TD-SIGN-001、TD-LINT-001（批次 1）
