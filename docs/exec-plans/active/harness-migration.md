# Harness 工程化改造计划

## 0. 元信息

- 项目 / 仓库：`量化数据源`（`/Users/likangjie/项目代码/量化数据源`）
- 分支：`harnessing`（基线在 `main`，提交 `07cae02`）
- 计划版本 / 日期：v1 / 2026-11-06
- 状态：**执行中**（阶段 1–3 已完成；阶段 4 批次 1 已完成，批次 2 待启动）
- 规则来源：`docs/HARNESS-RULES.md`（与 `~/references/harness-go` 哈希一致：`5d6820b1…`）

## 1. 项目概况

### 1.1 技术栈 / 构建 / 运行 / 部署

| 项 | 现状 |
|---|---|
| 语言 | Python（3.13.16，uv 托管解释器；代码用 `str \| None` 语法，要求 ≥3.10） |
| 依赖 | 运行：仅标准库；可选：`psycopg[binary]`（PostgreSQL 落库） |
| 构建 | 无构建系统（无 `pyproject.toml` / `Makefile`），脚本直接运行 |
| 运行 | `python3 tools/binance_pull.py ...`、`python3 tools/binance_user_stream.py ...`、`python3 tools/event_sink.py ...` |
| 部署 | 本地 CLI；无服务端组件、无发布产物 |
| 数据存储 | 输出文件（JSONL/CSV/SQLite）+ 可选 PostgreSQL（表结构 `sql/binance_stream_schema.sql`） |

### 1.2 顶层模块与入口点

```
量化数据源/
├── tools/                       # 业务实现（3 个可执行 CLI）
│   ├── binance_pull.py          # 公开行情 REST 拉取（K线/ticker/depth/exchangeInfo/symbols）
│   ├── binance_user_stream.py   # 私有实时推送（现货 WS API + 合约 listenKey）+ Key 校验/快照
│   └── event_sink.py            # 事件落库（JSONL/CSV/SQLite/PG）+ 策略信号引擎
├── sql/binance_stream_schema.sql# PG 6 张表 DDL（与代码内建表重复，见 TD-DUP-002）
├── scripts/analysis/            # 阶段 1 只读扫描器与缺陷复现脚本
├── docs/                        # 规则/计划/CI 判定/裁剪后的工程文档
├── 币安数据源分析报告.md          # 逆向分析主报告（离线证据产物）
├── 用户数据流接入指南.md          # 私有推送接入指南
├── README.md
└── work/                        # 逆向证据与私有数据（.gitignore，见 TD-DOC-002）
```

入口点共 3 个（`tools/*.py` 的 `main()`）；无库入口、无 `__init__.py`、无包结构。

### 1.3 当前测试与 CI 现状（阶段 3 后）

- 测试：`tests/` 已建立（20 个用例：签名官方向量、事件归一化、sink 幂等、信号状态机、CLI 冒烟、P0 回归 xfail）。
- 门禁：`bash scripts/gates/check.sh` 一键跑 6 步（compileall → ruff 基线 → pytest → 文档 → 生成物 → 密钥）；
  `ruff` 采用迁移基线（5 条存量违规，只拦新增）。
- CI：GitHub Actions 两个作业——`docs.yml`（文档）与 `ci.yml`（质量门禁），公开仓库免费额度下已跑通。
- 代码度量（阶段 1 扫描快照 `docs/exec-plans/active/scan/scan-report.md`）：受版本控制文件 12 个，Python 2,643 行 / 5 个 `.py`，112 个函数；跨文件重复窗口 2 组。

## 2. 框架判定与 CI 现状（见 §3.2）

- **判定结果：其他（非 Tauri）**
- 判定证据（逐条核对）：
  - 不存在 `src-tauri/tauri.conf.json`
  - 不存在 `src-tauri/Cargo.toml`
  - 不存在根 `package.json`（因此无 `@tauri-apps/cli` / `@tauri-apps/api`）
  - 实际为 Python CLI + SQL + Markdown
- 现有 `.github/workflows/`：**无**；无发布链路（无 tag/release 流程）。
- 落盘文档：`docs/CI.md`（含判定依据、现有 CI 表、Tauri 三问标注“不适用”）。
- 结论：**不触发 §3.3 交互询问**；GitHub CI 平台决策留到阶段 3（D1）。

## 3. 现状诊断

### 3.1 架构现状（模块依赖）

```
binance_user_stream.py ──(sys.path hack)──> event_sink.py ──> sqlite3 / 可选 psycopg
        │                                         │
        ├──> 内置最小 WS 客户端                     └──> SignalEngine（订单/持仓/PNL）
        └──> REST(userDataStream/subscribe.signature, fapi/dapi listenKey)

binance_pull.py（独立，自带 HTTP 客户端/重试/分页）
        └──> 与 binance_user_stream 的 http_json/sign_rest 重复（TD-ARCH-001）

sql/binance_stream_schema.sql ──(手工同步)──> event_sink.py::ensure_schema（TD-DUP-002）
```

问题：没有共享客户端层；`event_sink` 同时是库与 CLI；`user_stream` 通过 `sys.path` 拼接导入（TD-ARCH-002）；三个脚本各自硬编码 9/15 处 Binance 主机与 URL（改动扩散）。

### 3.2 复杂度热点（扫描器输出）

| 文件:行 | 函数 | 行数 | 分支 | 近似 CC | 嵌套 |
|---|---|---:|---:|---:|---:|
| `tools/binance_pull.py:317` | `cmd_klines` | 93 | 26 | 27 | 3 |
| `tools/binance_user_stream.py:466` | `cmd_check` | 80 | 19 | 20 | 4 |
| `tools/event_sink.py:666` | `cmd_selftest` | 78 | 21 | 22 | 5 |
| `tools/event_sink.py:90` | `normalize` | 66 | 23 | 24 | 6 |
| `tools/binance_user_stream.py:663` | `_futures_listen` | 72 | 21 | 22 | 5 |

### 3.3 重复代码

- 扫描器命中 2 组跨文件 8 行重复窗口：`binance_user_stream.py:332-333` ↔ `event_sink.py:581-582`，即两套 sink fan-out（`StreamWriter` vs `MultiSink`，TD-DUP-001）。
- 人工确认的重复：HTTP 客户端与重试（TD-ARCH-001）、DDL（TD-DUP-002）、规则文档三份（TD-DOC-001）。

### 3.4 文档缺口

- 无 `AGENTS.md`、`ARCHITECTURE.md`、`core-beliefs.md`（TD-DOC-003）。
- `README.md` 引用 `work/` 证据 17 处，但 `work/` 已 gitignore，clone 后断链（TD-DOC-002）。
- 规则文档三份并存、两份同哈希（TD-DOC-001）。

### 3.5 测试缺口

- 零自动化测试；关键缺陷（TD-RUNTIME-001）靠阶段 1 临时脚本才发现。
- 已有可测试资产未被利用：官方签名测试向量（`binance_user_stream.py:391` 内置）、11 条事件样例（`event_sink.py:666` 内置）、SQLite/PG 落库幂等语义。

### 3.6 安全与性能风险

- P0：多市场监听共享 DB 连接/信号状态，跨线程写入崩溃或数据竞争（TD-RUNTIME-001/002，已复现）。
- P1：DSN 经命令行明文传递（TD-SEC-001）；无静默流看门狗（TD-REL-001）。
- P2：每事件 commit/print（TD-PERF-001）；无依赖锁定（TD-DEP-001）。
- 未发现硬编码真实密钥；扫描 6 处命中均为文档占位符（TD-SEC-002）。

## 4. 改造批次划分

| 批次 | 覆盖业务域 | 主要目标 | 依赖前置 | 回滚方案 |
|---|---|---|---|---|
| 批次 1 ✅ | 运行时可靠性（`binance_user_stream` + `event_sink` 写入路径） | 修复 P0 并发缺陷；加静默流看门狗与优雅退出；回归测试 | 阶段 3 门禁就位；TD-TEST-001 的最小回归用例 | `git revert` 批次提交即可；无 schema 迁移、无数据变更；回滚后回到“单市场可用、多市场落库不可用”的既有状态 |
| 批次 2 | 共享客户端与工程结构 | 抽 `binance_client`（REST/签名/重试/限频）；包化 + `pyproject`；消除 `sys.path` hack 与 fan-out 重复 | 批次 1 完成（避免冲突）；D2 决策 | `git revert` 批次提交；保留旧 CLI 参数与输出格式（先对拍后切换），旧脚本可回退 |
| 批次 3 | 质量门禁 | pytest 用例集、pre-commit/CI、密钥扫描白名单、依赖锁定 | D1、D5 决策 | 删除新增门禁文件/配置；不改业务逻辑，回滚不影响运行 |
| 批次 4 | 文档与知识 | 建立 `AGENTS.md`/`ARCHITECTURE.md`/`core-beliefs.md`；收敛规则文档；证据保留策略 | 阶段 2 文档对齐完成 | `git revert` 文档提交；无代码影响 |
| 批次 5 | 性能与整洁 | 批量提交、日志分级、DDL 单一事实源、复杂度拆分 | 批次 2 完成 | `git revert`；DDL 切换需同时回滚 `sql/` 与代码读取逻辑，回滚前导出备份 |

> 批次 1 是唯一改变运行时行为的批次（bug 修复）；其余为纯重构/工程化，验收以“行为不变 + 门禁通过”为准。

## 5. 五阶段任务拆解

### 阶段 1 · 全量扫描与问题清单（本次，**已完成，待确认**）

| 子任务 | 负责人角色 | 产出物 | 机械验收 |
|---|---|---|---|
| 仓库地图 / 框架判定 | 架构审计者 | 本文件 §1–§2、`docs/CI.md` | 文件路径存在；判定证据逐条可查 |
| 架构/复杂度/重复扫描 | 架构审计者 | `docs/exec-plans/active/scan/scan-report.md`、`scan.json` | `python3 scripts/analysis/scan_project.py` 在阶段 1 提交 `474e382` 上可复跑，summary 计数与提交版一致（`generated_at` 除外） |
| 缺陷复现 | 质量工程师 | `scripts/analysis/repro_thread_safety.py` + 本清单 P0 记录 | 脚本退出码 0（复现成功） |
| 问题清单 | 质量工程师 | `docs/exec-plans/tech-debt-tracker.md` | 每条含 11 字段；P0/P1 均有 file:line 证据 |
| 批次与回滚方案 | 架构审计者 | 本文件 §4 | 每批有独立回滚方案 |
| 业务代码零改动自证 | 架构审计者 | `git diff --stat`（见 §7） | 对 `tools/ sql/` 的 diff 为空 |

**阶段 1 验收勾选**：

- [x] 五个阶段全部拆解完成，每个子任务都有负责人角色、产出物路径、可机械检查的验收标准
- [x] 框架判定已完成，命中证据（文件路径）写入 `docs/CI.md`
- [x] 问题清单每条含 ID、位置、类别、严重度、证据、修复建议、业务行为影响
- [x] 标注了“bug 修复”与“业务变更”两类（本清单 21 项中 4 项为 bug 修复，0 项业务变更）
- [x] 每批改造有独立回滚方案
- [x] 计划文档无“只有标题、没有分析”的条目
- [x] 未修改任何业务代码（`git diff --stat` 自证）

### 阶段 2 · 文档对齐（**已完成，2026-11-06**）

- 前置：阶段 1 计划已确认（D1–D4 已由用户决策）。
- 产出：`AGENTS.md`、`ARCHITECTURE.md`、`docs/index.md`、`docs/design-docs/{index,core-beliefs,decisions}.md`、
  `docs/product-specs/index.md`、`docs/references/index.md`、`docs/QUALITY_SCORE.md`、`docs/RELIABILITY.md`、
  `docs/SECURITY.md`、`docs/DEVELOPMENT.md`、`docs/TROUBLESHOOTING.md`、`docs/generated/db-schema.md`、
  `docs/exec-plans/completed/README.md`、`scripts/docs/{check_docs,gen_db_schema}.py`、`.github/workflows/docs.yml`。
- 子任务与产出：
  | 子任务 | 负责人角色 | 产出物 | 机械验收 |
  |---|---|---|---|
  | 重写 `AGENTS.md` | 文档负责人 | `AGENTS.md`（附录 E 目标形态） | 新会话按其中命令可跑通 `selftest` |
  | 架构文档 | 架构审计者 | `ARCHITECTURE.md`（模块边界、数据流、失败模式） | 与 `scan.json` 依赖图一致 |
  | 价值契约 | 项目负责人 | `core-beliefs.md`（附录 F） | 每条可追溯到一次决策或缺陷 |
  | 文档索引与 README 重写 | 文档负责人 | `README.md`、`docs/README.md` | 失效路径 0；`work/` 获取方式写清 |
  | exec-plans 结构 | 质量工程师 | `docs/exec-plans/{active,completed}/`、本计划与 tracker 就位 | 目录存在且链接可达 |
- 验收：`python3 scripts/docs/check_docs.py` 通过（22 个文档、24 条链接、索引完整、生成物一致）；
  AGENTS.md 行数与必需小节满足规则；doc check CI 作业已落 `.github/workflows/docs.yml`。

**阶段 2 验收勾选**：

- [x] `AGENTS.md` ≤ 200 行、含必需小节（地图形态，不写教程）
- [x] `ARCHITECTURE.md` 依赖方向规则与代码抽样 4 处一致
- [x] `docs/index.md` 链接全部可解析（检查器实测 24 条）
- [x] 旧文档逐条比对：README 重写、重复规则文档收敛为 `docs/HARNESS-RULES.md` 单份
- [x] `QUALITY_SCORE.md` 给出业务域/架构层分数与可复算依据
- [x] 文档校验在死链/缺索引/生成物漂移时失败（负向测试：坏链接退出码 1）

### 阶段 3 · 门禁审计与自动化质量校验（**已完成，2026-11-07**）

- 前置：阶段 2 通过。
- 子任务：
  | 子任务 | 负责人角色 | 产出物 | 机械验收 |
  |---|---|---|---|
  | 语法/导入门禁 | 质量工程师 | `scripts/gates/check.sh`（compileall + import 冒烟） | 故意植入语法错误时退出非 0 |
  | 单测门禁 | 质量工程师 | `pytest` 配置 + `tests/` 骨架 | `pytest -q` 在干净 venv 通过 |
  | 密钥扫描门禁 | 安全审计者 | 扫描器 + `.secretsignore` | 植入假密钥能命中，文档占位符不误报 |
  | pre-commit / CI | 质量工程师 | `.pre-commit-config.yaml` 或 `.github/workflows/`（D1 决策） | 在干净 clone 上可复现 |
  | 依赖锁定 | 质量工程师 | `requirements*.txt` / uv lock（D5） | 锁定安装后 selftest 通过 |
  | §3.3 Tauri 三问 | — | 不适用 | 已在 `docs/CI.md` 标注 |
- 产出（已落地）：
  - `scripts/gates/check.sh`（六步门禁，本地与 CI 同一脚本）
  - `scripts/gates/ruff_gate.py` + `scripts/gates/ruff_baseline.txt`（迁移基线：5 条存量，禁新增）
  - `tests/`（20 用例；P0 回归以 `xfail(strict)` 记录，修复后自动失败以提醒转正）
  - `.secretsignore` + `scan_project.py --check-secrets`（10 处命中全部为占位符/白名单，0 剩余）
  - `requirements-dev.txt`（pytest/ruff 锁定）、`requirements-pg.txt`（psycopg 锁定）
  - `.github/workflows/ci.yml`（GitHub Actions 质量门禁）
- 验收：`bash scripts/gates/check.sh` 一条命令全过；负向测试通过（死链/假密钥/新增 lint 均能拦）；
  GitHub Actions `ci` 与 `docs` 两个作业在 `harnessing` 上绿灯。

**阶段 3 验收勾选**：

- [x] 语法/导入门禁：故意植入语法错误时退出非 0（compileall）
- [x] 单测门禁：`pytest -q` 20 用例通过（18 passed + 2 xfailed 记录 P0/签名缺陷）
- [x] 密钥扫描门禁：植入假 AWS key 退出 1；文档占位符 0 误报
- [x] CI：GitHub Actions `ci.yml` + `docs.yml` 已运行（公开仓库免费额度）
- [x] 依赖锁定：`requirements-dev.txt` / `requirements-pg.txt` 固定版本
- [x] ruff 引入（D5）：仅 lint，基线机制避免一次性改业务代码
- [x] §3.3 Tauri 三问：不适用（非 Tauri），已在 `docs/CI.md` 标注

### 阶段 4 · 问题修复与重构（**批次 1 已完成，2026-11-07**）

- 前置：阶段 3 通过（护栏就位后才允许动业务代码）。
- 批次 1 已完成：单写线程 + 有界队列（TD-RUNTIME-001/002）、静默看门狗与可中断退避（TD-REL-001/002）、
  REST/WS 签名拆分（TD-SIGN-001）、ruff 基线清零（TD-LINT-001）；P0 回归测试转正，门禁全绿。
- 按批次推进（§4）：批次 1 ✅ → 批次 2（包化，待启动）→ 批次 5（性能项在阶段 5 后可选）。
- 每批流程：先补回归测试 → 修复 → 门禁全绿 → 出具“行为对比”证据 → 提交。
- 验收（每批独立）：`git diff` 只涉及声明范围；门禁通过；P0/P1 项在 tracker 中状态更新；批次 1 需附并发写入 60s 冒烟日志。

### 阶段 5 · 测试补全与门禁接入

- 前置：阶段 4 批次 1/2 完成。
- 子任务：
  | 子任务 | 负责人角色 | 产出物 | 机械验收 |
  |---|---|---|---|
  | 补齐无测试模块 | 质量工程师 | `tests/test_pull.py`、`test_user_stream.py`、`test_event_sink.py` | 覆盖三个 CLI 的参数/错误码/落库语义 |
  | 边界与异常用例 | 质量工程师 | 断线重连、429/418、空 K 线、过期 listenKey 用例 | 用例可稳定复现（非 flaky） |
  | 覆盖率门槛 | 质量工程师 | 覆盖率报告 + 阈值 | 核心模块 ≥70%，P0 路径 100% |
  | 门禁接入 CI | 质量工程师 | 门禁接入 D1 选定平台 | PR 上真实拦截失败 |
- 验收：`pytest` + 门禁一键通过；失败用例能定位到文件:行；覆盖率报告入库（或归档链接）。

## 6. 待人工决策清单

| 编号 | 问题 | 为什么需要人判断 | 影响范围 |
|---|---|---|---|
| D1 | 是否建立 CI，用 GitHub Actions 还是仅本地 pre-commit？ | **已决策（2026-11-06）：GitHub Actions**；阶段 2 先落文档作业，阶段 3 扩展完整门禁 | 阶段 3、批次 3 |
| D2 | 是否包化（`pyproject.toml` + `binance_tools/` 包 + `python -m` 入口）？ | **已决策：包化**；`tools/*.py` 保留薄壳兼容 | 批次 2 |
| D3 | `work/`（逆向证据约 1GB，含 App 配置 AK/SK、Cookie 副本）如何保留？ | **已决策：本地正常保留、不入库**（ADR-007）；README/参考索引说明再生成方式 | 批次 4、TD-DOC-002 |
| D4 | 默认落库目标是 SQLite 还是 PostgreSQL（或双写）？ | **已决策：双写**（ADR-004）；默认 `jsonl,csv,sqlite`，生产追加 `pg` | 批次 1/5、TD-PERF-001 |
| D5 | 是否引入 ruff/mypy 及严格度？ | **已决策：引入 ruff（仅 lint、不格式化）；暂不引入 mypy**（ADR-006 关联） | 阶段 3、批次 3 |
| D6 | 三个脚本是否合并为单一 CLI（`binance-tools klines|listen|snapshot`）？ | 待决策（建议随 D2 一并定） | 批次 2、TD-ARCH-003 |

## 7. 进度与决策日志

| 日期 | 阶段 | 动作 | 关联 commit | 决策与理由 |
|---|---|---|---|---|
| 2026-11-06 | 基线 | `git init` + 基线提交（11 文件，6,216 行） | `07cae02`（main） | 为阶段 1 的“零业务改动”自证建立版本基线；`.gitignore` 排除 `.venv/`、`work/`、私有目录 |
| 2026-11-06 | 阶段 1 | 只读扫描 + P0 复现 + 三份文档 | 待提交（`harnessing`） | 扫描器/复现脚本入库；计划与问题清单待人工确认 |
| 2026-11-06 | 阶段 1 | 业务代码零改动自证 | — | `git diff --stat -- tools/ sql/` 为空；本阶段新增仅 `docs/`、`scripts/analysis/`、`.gitignore` 调整 |
| 2026-11-06 | 决策 | D1–D4 用户拍板（ADR-004/005/006/007） | — | CI=GitHub Actions；包化；work/ 本地保留；落库双写 |
| 2026-11-07 | 决策 | D5：引入 ruff（仅 lint，不上 mypy） | — | 用户拍板；采用迁移基线，不改业务代码 |
| 2026-11-07 | 批次 1 | 单写线程/看门狗/签名拆分/ruff 清零；6 个 TD 完成 | 待提交 | 并发回归转正；`repro_thread_safety.py` 退出码 1（未复现） |
| 2026-11-07 | 阶段 3 | 门禁体系落地：gate 脚本 + pytest + ruff 基线 + 密钥门禁 + 依赖锁定 + CI | 待提交 | 本地 `check.sh` 全绿；GitHub Actions 两个作业已验证 |
| 2026-11-06 | 阶段 2 | 文档对齐完成：AGENTS/ARCHITECTURE/索引/信念/ADR/规格/质量/可靠/安全/开发/排障/生成物 + 校验器 + CI 作业 | 待提交 | `check_docs.py` 通过；重复规则文档收敛；README 重写并说明 work/ 本地策略 |

### 附：阶段 1 执行时的工作区自证

```console
$ git diff --stat 07cae02..HEAD -- tools/ sql/      # 预期：空
$ git status --short                                 # 预期：仅 docs/ scripts/ 的新增
```
