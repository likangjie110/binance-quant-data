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

## 2. 当前代码结构与依赖方向

```
tools/binance_pull.py        （独立，仅标准库）
        │  urllib / ssl / csv
        ▼
   Binance 公共 REST（api/fapi/dapi/eapi）

tools/binance_user_stream.py （CLI + WS 客户端 + REST 私有调用）
        │  sys.path 注入后 import
        ▼
tools/event_sink.py          （归一化 + sinks + 信号引擎）
        │                         │
        │ sqlite3（标准库）        └─► 可选 psycopg（PG，lazy import）
        ▼
   SQLite / PostgreSQL

scripts/analysis/*、scripts/docs/*  （只依赖标准库，不被运行时代码依赖）
```

### 依赖方向规则（可机械核对）

1. **单向**：CLI → 处理层 → 适配器（HTTP/WS/DB）→ 标准库；反向依赖一律禁止。
2. **只有处理层能跨脚本复用**：目前唯一合法跨脚本依赖是 `binance_user_stream → event_sink`；
   新增依赖必须登记到本文件，否则视为违规（TD-ARCH-002 修复后改为包内相对导入）。
3. **签名只在一个地方**：目前 `sign_rest()` 在 `binance_user_stream.py:109`；批次 2 收敛到 `client` 模块，
   其他模块不得自行拼签名。
4. **DB 连接只在 sink 内、且只在 writer 线程**：SQLite 连接在 `event_sink.py:321`，PG 连接在 `event_sink.py:336`（lazy 导入）；
   监听线程只入队（`StreamWriter.write`），sink 由 writer 线程创建与关闭（批次 1）。
5. **原始交易所字段只在归一化层解析**：`event_sink.normalize()`（`event_sink.py:90`）是唯一读裸字段的入口；
   sinks/信号只消费归一化结构。
6. **只读不变量**：全仓库不存在下单/撤单/提币调用；私有 Key 仅用于查询与订阅。

### 与代码的抽样核对（阶段 2 验收）

| 规则 | 代码证据 | 结论 |
|---|---|---|
| 跨脚本依赖唯一 | `tools/binance_user_stream.py:67`（`sys.path.insert` + `from event_sink import ...`） | 一致 |
| 可选依赖边界清晰 | `tools/event_sink.py:326` `PgBackend`；`:336` 内 `import psycopg`（lazy） | 一致 |
| 公开拉取不依赖内部模块 | `tools/binance_pull.py:32-45` 仅标准库；`:160` 自带 HTTP 客户端 | 一致（同时暴露重复问题 TD-ARCH-001） |
| DB 只在 sink | `tools/event_sink.py:321`（SQLite）、`:336`（PG）、`:348` `SqlSink` | 一致 |

## 3. 目标结构（批次 2 / D2 包化后）

```
binance_tools/
├── __init__.py
├── config.py      # 主机、路径、端点常量（唯一事实源）
├── client.py      # REST：签名、超时、重试、限频预算
├── ws.py          # 最小 RFC6455 客户端（现 binance_user_stream 内置）
├── public.py      # 公开行情（现 binance_pull 主体）
├── private.py     # 私有订阅（现 binance_user_stream 主体）
├── sinks.py       # JSONL/CSV/SQLite/PG（现 event_sink 的 sink 部分）
├── signals.py     # SignalEngine（现 event_sink）
├── normalize.py   # 事件归一化
└── cli.py         # argparse 分发（klines|listen|snapshot|selftest|replay）
pyproject.toml     # requires-python>=3.10；extras: pg / dev；console_scripts: binance-tools
tests/             # pytest：签名向量、归一化、sink 幂等、信号状态机、并发回归
```

迁移期保留 `tools/*.py` 薄壳（`from binance_tools.cli import main`），保证旧命令不变。

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
