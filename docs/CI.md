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
| （无） | — | — | — | 仓库无 `.github/workflows/`，无任何 CI 配置 |

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
- 阶段 3 计划建立的基础门禁（本地可复现，先不绑定具体 CI 平台）：
  1. `python3 -m compileall tools scripts`（语法门禁）
  2. `python3 -m pytest`（阶段 5 前为最小冒烟：签名测试向量、事件归一化、sink 幂等）
  3. `python3 scripts/analysis/scan_project.py`（密钥/凭证扫描）
  4. `git diff --stat` 守卫（业务代码改动必须显式声明）
- 不生成 `.github/workflows/` 打包发布流水线：本项目是 CLI 工具集，没有桌面端产物。

## 5. 变更历史

| 日期 | 变更 | 原因 |
|---|---|---|
| 2026-11-06 | 建立本文件 | harness 阶段 1 要求 |
