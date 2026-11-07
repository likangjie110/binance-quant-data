# AGENTS.md

> 本文件是**内容目录**，不是百科全书。需要细节时，按下方指引跳转。

## 这是什么项目

币安行情/私有推送的本地数据工具集：先用 REA 逆向桌面端确认数据源，再提供 **公开行情拉取**、
**官方 API Key 私有实时推送**、**事件落库 + 策略信号**。面向个人量化研究，**只读，不包含交易下单**。

> 当前处于 harness 工程化改造中：分支 `harnessing`，计划见 `docs/exec-plans/active/harness-migration.md`。
> 阶段 1–3 已完成；批次 1（并发/看门狗/签名）与批次 2（包化/共享客户端）已完成。

## 如何开始

- 架构总览：`ARCHITECTURE.md`
- 核心信念与裁决依据：`docs/design-docs/core-beliefs.md`
- 关键决策（ADR）：`docs/design-docs/decisions.md`
- 产品范围与验收：`docs/product-specs/index.md`
- 当前执行计划：`docs/exec-plans/active/`
- 已知技术债：`docs/exec-plans/tech-debt-tracker.md`
- CI 与发布决策：`docs/CI.md`
- 全部文档索引：`docs/index.md`

## 硬性约束（不可违反）

1. **核心零依赖**：`binance_tools/` 与 `tools/` 只允许 Python 标准库；PostgreSQL 是可选 extras（`psycopg[binary]`），不得变成必需依赖。
2. **只读**：不得实现下单、撤单、划转、提币；私有 Key 仅用于查询与订阅。
3. **密钥不落盘、不打印**：只从环境变量或 `chmod 600` 文件读取；`work/`、`.env`、`*key*.txt` 已在 `.gitignore`。
4. **私有数据不进版本库**：`work/`（含 App 配置、Cookie 副本、逆向证据）只保留在本地（D3 决策）。
5. **请求层纪律**：所有公网请求必须有超时、重试与限频预算；429/418/5xx 一律退避。
6. **合约 WS 路由**：必须用 `/market`（行情）、`/public`（盘口）、`/private`（用户数据）前缀；旧 `/ws/` 只推 `/public` 数据。
7. **单写线程**：落库/信号只允许 writer 线程持有 DB 连接；监听线程只入队（已实现，`--queue-size` 有界背压）。
8. **文档与代码同提交**：行为/接口变化必须同步更新对应 `docs/`；计划写在 `docs/exec-plans/active/`，完成后移入 `completed/`。

## 常用命令

```bash
# 安装为命令（可选）：pip install -e . → binance-tools
# 或无需安装：python3 -m binance_tools
python3 -m binance_tools selftest                    # 无密钥自检：签名向量 + 公共 WS
python3 -m binance_tools check                       # API Key 权限/私有流校验
python3 -m binance_tools listen --markets spot,um --out work/private --sink jsonl,csv --signals
python3 -m binance_tools klines --market spot --symbol BTCUSDT --interval 1h --limit 24
python3 tools/binance_pull.py --help                 # 旧脚本薄壳仍可用

# PostgreSQL 落库（可选依赖，独立 venv）
python3 -m venv .venv && .venv/bin/pip install "psycopg[binary]"
.venv/bin/python -m binance_tools sink-selftest --out work/signals/selftest --pg-dsn "$BINANCE_PG_DSN"

# 质量门禁（一键；CI 跑同一脚本）
bash scripts/gates/check.sh
# 单项
python3 -m compileall -q binance_tools tools scripts tests
.venv/bin/python -m pytest -q
python3 scripts/docs/check_docs.py                  # 文档链接/结构/新鲜度检查
python3 scripts/analysis/scan_project.py --out docs/exec-plans/active/scan
python3 scripts/analysis/repro_thread_safety.py     # P0 回归反证（退出码 1 = 未复现/已修复）
```

## 目录地图

| 路径 | 职责 |
|---|---|
| `binance_tools/` | 包：cli/public/private/client/ws/signing/sinks/signals/normalize（批次 2） |
| `tools/` | 三个兼容薄壳（旧命令转发到 `binance_tools.cli`） |
| `sql/` | PostgreSQL 表结构（单一事实源，DDL 代码内副本待合并，TD-DUP-002） |
| `scripts/analysis/` | 只读扫描器与缺陷复现脚本，不属于运行时代码 |
| `scripts/docs/` | 文档校验器（链接/结构/新鲜度） |
| `docs/` | 知识库：设计、计划、规格、参考、质量评分（索引见 `docs/index.md`） |
| `docs/exec-plans/` | 进行中/已完成的改造计划与技术债台账 |
| `work/` | 本地逆向证据与私有数据（**不入库**，D3：正常保留在本地） |

## 下一步去哪儿看

- 动手改代码前：`docs/exec-plans/active/harness-migration.md` → 当前批次与回滚方案
- 判断"该不该这么做"：`docs/design-docs/core-beliefs.md` + `docs/design-docs/decisions.md`
- 接口/数据源细节：`币安数据源分析报告.md`、`用户数据流接入指南.md`
- 故障排查：`docs/TROUBLESHOOTING.md`、`docs/RELIABILITY.md`

## 工作方式

- 一次只推进一步；先读相关文档，再改代码；改完同步文档与计划日志。
- 提交粒度单一职责；重构与行为变更分开提交（bug 修复必须附复现/回归证据）。
- 交互式决策必须落盘：确认过但不写进仓库的决策等于没做。
- 发现新问题先登记到 `tech-debt-tracker.md`，不要在扫描阶段顺手修。
