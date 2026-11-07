# 开发指南

> 面向在本仓库改代码的人/智能体。先读 `AGENTS.md` 拿地图，再读本文件动手。

## 1. 环境要求

| 项 | 要求 |
|---|---|
| Python | ≥ 3.10（代码使用 `str \| None` 语法；本机 3.13.16） |
| 依赖 | 运行：仅标准库；PostgreSQL 落库：`psycopg[binary]`（可选，装进独立 `.venv`） |
| 平台 | macOS / Linux；Windows 未验证 |
| 网络 | 需能访问币安域名；本机可能经代理（见 `TROUBLESHOOTING.md` 的 fake-IP 说明） |

```bash
# 可选：PostgreSQL 落库环境
python3 -m venv .venv
.venv/bin/pip install "psycopg[binary]"
```

## 2. 目录与入口

- 代码包：`binance_tools/`（cli/public/private/client/ws/signing/sinks/signals/normalize/common/config）
- 兼容薄壳：`tools/*.py`（转发到 `binance_tools.cli`，旧命令保持不变）
- 脚本：`scripts/analysis/`（分析/复现）、`scripts/docs/`（文档校验）、`scripts/gates/`（门禁）
- 知识库：`AGENTS.md`、`ARCHITECTURE.md`、`docs/`（索引 `docs/index.md`）
- 数据：`sql/`（PG DDL）；运行产物 `work/`（**不入库**）

三种运行方式（行为一致）：

```bash
pip install -e .                       # 方式 1：安装后使用 binance-tools
binance-tools klines --market spot --symbol BTCUSDT --interval 1h --limit 24

python3 -m binance_tools selftest       # 方式 2：无需安装（仓库根执行）
python3 tools/binance_user_stream.py selftest   # 方式 3：旧脚本薄壳
```

## 3. 测试与门禁

| 阶段 | 测试方式 |
|---|---|
| 一键门禁 | `bash scripts/gates/check.sh`（compileall → ruff 基线 → pytest → 文档 → 生成物 → 密钥） |
| 单测 | `.venv/bin/python -m pytest -q`（24 用例：签名双向量、归一化、sink 幂等、信号状态机、并发回归、看门狗、CLI 冒烟） |
| lint | `.venv/bin/ruff check tools scripts tests`；门禁走 `scripts/gates/ruff_gate.py`（迁移基线只拦新增） |
| P0 回归 | `python3 scripts/analysis/repro_thread_safety.py`：修复前退出码 0（复现），修复后 1（不再复现） |

CI（GitHub Actions）：`.github/workflows/ci.yml`（质量门禁）+ `docs.yml`（文档）。公开仓库免费额度。
依赖：`requirements-dev.txt`（pytest/ruff）、`requirements-pg.txt`（psycopg）。

## 4. 调试

```bash
# 无密钥验证 WS 客户端与签名实现
python3 tools/binance_user_stream.py selftest

# 只读扫描（复杂度/重复/密钥）
python3 scripts/analysis/scan_project.py --root . --out /tmp/scan

# 事件落库不连网验证
python3 tools/event_sink.py selftest --out /tmp/sink
python3 tools/event_sink.py replay --file /tmp/sink/events_demo.jsonl --out /tmp/signals

# 私有流调试（需 Key）：先 check 再 listen，先单市场再扩多市场
python3 tools/binance_user_stream.py check --markets spot
python3 tools/binance_user_stream.py listen --markets spot --duration 60 --sink jsonl,csv
```

## 5. 提交与分支

- 分支：`main` 为基线；改造在 `harnessing`，按 `docs/exec-plans/active/harness-migration.md` 批次推进。
- 提交粒度：一个提交只做一件事；**重构与行为变更分开**；bug 修复附复现/回归证据。
- 提交信息：`type(scope): 摘要`（如 `fix(listen): 单写线程修复并发写库`）。
- 提交前：`git status --short` 确认无 `work/`、`.env`、密钥文件；跑一遍编译与文档校验。

## 6. 发布

本项目无构建产物、无发布流水线：

- 使用方式：`pip install -e .` 后使用 `binance-tools`，或 `python3 -m binance_tools`，或旧脚本薄壳。
- 版本标识：`pyproject.toml` 的 `version`（当前 0.2.0）；发布时以 git tag 标记。
- CI 只做质量门禁，不产出发布资产。

## 7. 文档工作流

1. 改行为 → 同步改 `docs/` 对应文件（`RELIABILITY`/`TROUBLESHOOTING`/指南）。
2. 改结构/依赖方向 → 更新 `ARCHITECTURE.md` 与抽样核对表。
3. 做决策 → 在 `docs/design-docs/decisions.md` 追加 ADR。
4. 新问题 → 登记 `docs/exec-plans/tech-debt-tracker.md`，不要顺手修。
5. 提交前 `python3 scripts/docs/check_docs.py`（链接/结构/生成物新鲜度）。
