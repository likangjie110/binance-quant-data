# CI 配置决定

## 1. 框架判定

- 判定结果：**其他（非 Tauri）**
- 判定依据（§3.2 机械判定，逐条核对）：
  - 无 `src-tauri/tauri.conf.json`
  - 无 `src-tauri/Cargo.toml`（无 Rust 工程）
  - 无根 `package.json`（无 `@tauri-apps/cli` / `@tauri-apps/api` 依赖）
  - 实际构成：纯 Python CLI（`tools/*.py`）+ SQL schema + Markdown 文档；运行时依赖 Python 3.10+ 标准库，PostgreSQL 落库为可选依赖 `psycopg3`
- 判定日期：2026-11-06
- 证据文件：
  - `/Users/likangjie/项目代码/量化数据源/tools/binance_pull.py`
  - `/Users/likangjie/项目代码/量化数据源/tools/binance_user_stream.py`
  - `/Users/likangjie/项目代码/量化数据源/tools/event_sink.py`
  - `/Users/likangjie/项目代码/量化数据源/sql/binance_stream_schema.sql`
  - 反证（应存在但不存在的路径）：`src-tauri/`、`package.json`、`Cargo.toml`

> 说明：判定为「其他」时，**不触发 §3.3 的 Tauri 三步交互询问**（是否生成 GitHub CI / 目标平台 / Release 方式），本节第 3 部分标注为不适用。

## 2. 现有 CI 现状（存量项目必填）

| 文件 | 触发条件 | 覆盖平台 | 是否自动发布 | 备注 |
|---|---|---|---|---|
| `.github/workflows/docs.yml` | push `main`/`harnessing`（路径过滤：docs/AGENTS/ARCHITECTURE/sql/scripts/docs） | ubuntu-latest | 否 | 文档结构/链接/占位符 + 生成物一致性 |
| `.github/workflows/ci.yml` | push `main`/`harnessing` 与 PR | ubuntu-latest | 否 | `scripts/gates/check.sh` 六步门禁（compileall/ruff 基线/pytest/文档/生成物/密钥） |

补充现状：

| 项 | 现状 |
|---|---|
| 版本控制 | 2026-11-06 首次 `git init`，基线提交 `07cae02`；改造在 `harnessing` 分支进行 |
| 构建系统 | 无（无 `pyproject.toml` / `setup.py` / `Makefile`） |
| 依赖声明 | 无（仅注释说明 Python 标准库；PG 可选依赖 `psycopg[binary]`，装在 `.venv`） |
| 测试框架 | 无（仅各脚本内的 `selftest` 子命令，需手工运行） |
| 发布链路 | 无（无 tag / release 流程；脚本直接分发使用） |
| 代码风格门禁 | 无（无 ruff/flake8/black 配置） |

## 3. 交互确认记录（仅 Tauri 填写）

| 问题 | 用户回答 | 时间 |
|---|---|---|
| 是否生成 GitHub CI 配置 | 不适用（非 Tauri） | — |
| 目标平台（多选） | 不适用 | — |
| Release 发布方式 | 不适用 | — |

## 4. 落地说明

- 本阶段只记录框架判定与 CI 现状，**不做 CI 决策**（决策留到阶段 3，见 `harness-migration.md` 第 6 节 D1）。
- 已落地门禁（本地与 CI 同一脚本 `scripts/gates/check.sh`）：
  1. `python3 -m compileall`（语法门禁）
  2. `python3 scripts/gates/ruff_gate.py`（ruff lint，迁移基线 5 条存量，只拦新增）
  3. `python3 -m pytest`（20 用例：签名向量/归一化/幂等/信号/CLI/P0 xfail）
  4. `python3 scripts/docs/check_docs.py`（文档结构/链接/占位符）
  5. `python3 scripts/docs/gen_db_schema.py --check`（生成物一致性）
  6. `python3 scripts/analysis/scan_project.py --check-secrets`（密钥扫描，未忽略命中即失败）
- 依赖锁定：`requirements-dev.txt`（pytest/ruff）、`requirements-pg.txt`（psycopg）。
- 不生成打包发布流水线：本项目是 CLI 工具集，没有桌面端产物。

## 5. 变更历史

| 日期 | 变更 | 原因 |
|---|---|---|
| 2026-11-06 | 建立本文件 | harness 阶段 1 要求 |
| 2026-11-07 | 新增 `ci.yml` 质量门禁；补 `docs.yml` 与依赖锁定 | 阶段 3 门禁落地（D1/D5） |
