# 量化数据源 · 币安工具集

用 REA 逆向币安桌面端确认数据源，并提供一套**只读**的本地数据工具：

1. **公开行情拉取**：现货 / U 本位 / 币本位 / 期权的 K 线、ticker、盘口、交易规则 → CSV/JSON。
2. **私有实时推送**：用你自己的只读 API Key 订阅订单/成交/余额/持仓事件（现货 WS API + 合约 listenKey）。
3. **事件落库与策略信号**：JSONL / CSV / SQLite / PostgreSQL 四类落盘 + 订单/持仓/已实现盈亏信号。

> 本项目**不包含任何交易执行能力**（无下单/撤单/划转/提币），私有 Key 仅用于查询与订阅。

## 当前状态

- 正在做 harness 工程化改造：分支 `harnessing`，计划见 [harness-migration](docs/exec-plans/active/harness-migration.md)。
- 阶段 1–3 已完成；阶段 4 批次 1（运行时可靠性）已完成：单写线程落库、静默流看门狗、REST/WS 签名拆分。
- 已知 P0 已清零；剩余改造为批次 2（包化）与质量补强（见 [tech-debt-tracker](docs/exec-plans/tech-debt-tracker.md)）。

## 快速开始

```bash
# 无密钥自检（签名向量 + 公共 WS）
python3 tools/binance_user_stream.py selftest

# 公开行情：现货 K 线
python3 tools/binance_pull.py klines --market spot --symbol BTCUSDT --interval 1h --limit 24

# 私有推送（需要 BINANCE_API_KEY / BINANCE_API_SECRET，或在 --key-file 指定）
python3 tools/binance_user_stream.py check
python3 tools/binance_user_stream.py listen --markets spot --sink jsonl,csv --signals --out work/private

# 事件落库自检（无需密钥）
python3 tools/event_sink.py selftest --out work/signals/selftest
```

PostgreSQL 落库（可选依赖，独立 venv）：

```bash
python3 -m venv .venv && .venv/bin/pip install "psycopg[binary]"
.venv/bin/python tools/event_sink.py selftest --out work/signals/selftest --pg-dsn "postgresql://user:pass@127.0.0.1:5432/quant"
```

## 文档地图

| 入口 | 内容 |
|---|---|
| [AGENTS.md](AGENTS.md) | 智能体入口地图（硬约束、命令、目录） |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 领域地图、依赖方向、目标包结构 |
| [docs/index.md](docs/index.md) | 全文档索引（设计与工程） |
| [币安数据源分析报告.md](币安数据源分析报告.md) | 数据源来自哪里、能否自取（REA 证据） |
| [用户数据流接入指南.md](用户数据流接入指南.md) | API Key、三条私有通道、落库与信号 |
| [docs/QUALITY_SCORE.md](docs/QUALITY_SCORE.md) | 质量评分与差距 |
| [docs/CI.md](docs/CI.md) | 框架判定与 CI 决定 |

## 环境与自检

- Python ≥ 3.10；核心只依赖标准库。
- 一键门禁：`bash scripts/gates/check.sh`（CI：`.github/workflows/ci.yml`；文档作业：`docs.yml`）。
- P0 回归反证：`python3 scripts/analysis/repro_thread_safety.py`（退出码 1 = 未复现/已修复）。
- 只读扫描：`python3 scripts/analysis/scan_project.py --out /tmp/scan`。

## 数据与安全

- `work/` 是**本机证据目录**（逆向产物、私有快照），已 gitignore；仓库内不放私有数据。
- 密钥只从环境变量或 `chmod 600` 文件读取；不打印、不提交。
- 细节见 [docs/SECURITY.md](docs/SECURITY.md) 与 [docs/RELIABILITY.md](docs/RELIABILITY.md)。

## 提交前

```bash
bash scripts/gates/check.sh   # compileall + ruff + pytest + 文档 + 生成物 + 密钥
git status --short            # 不应出现 work/、.env、*key*.txt
```
