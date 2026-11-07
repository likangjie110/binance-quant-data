# 质量评分（按业务域 / 架构层）

> 评分是**可复算**的：每个分数都对应可运行命令或可核对清单。目标不是好看，而是暴露差距。
> 更新方式：改动代码/文档后重跑下方"复算方式"，同步本表与差距。

## 1. 评分标尺（0–5）

| 分 | 含义 |
|---|---|
| 0 | 不存在 / 完全不可用 |
| 1 | 有雏形，但关键路径不可靠或有 P0 缺陷 |
| 2 | 主路径可用，缺自动化验证，已知缺陷未修 |
| 3 | 主路径稳定，有部分自动化或明确手工验收，无 P0 |
| 4 | 有自动化门禁覆盖，边界清晰，文档与代码一致 |
| 5 | 有机械强制（测试/门禁/监控），可长期自证 |

**加权**：测试 ×2、文档 ×1、复杂度 ×1、依赖方向 ×1、可靠性 ×2（合计权重 7）。
`加权分 = Σ(分数×权重)/7`。

## 2. 按业务域（批次 2 后）

| 业务域 | 测试 | 文档 | 复杂度 | 依赖方向 | 可靠性 | 加权分 | 目标 | 主要差距 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 公开行情拉取（`public.py`） | 1 | 4 | 3 | 5 | 4 | **3.14** | 4.0 | 无分页/限频专项测试；`cmd_klines` 仍 93 行/CC≈27 |
| 私有实时推送（`private.py`） | 4 | 4 | 2 | 4 | 4 | **3.71** | 4.0 | 无真实 Key 集成测试（离线环境限制）；`cmd_check` 偏长 |
| 事件落库（`sinks.py`） | 4 | 4 | 2 | 4 | 4 | **3.71** | 4.0 | PG 未进 CI；每事件 commit（批次 5） |
| 策略信号（`signals.py`） | 3 | 3 | 2 | 3 | 4 | **3.14** | 4.0 | 无长期回放对拍；与 sinks 的边界可再收紧 |
| 数据源逆向证据 | 1 | 4 | 4 | 5 | 3 | **3.00** | 3.5 | 证据依赖本地 `work/`（D3 约定）；无自动复跑校验 |
| 工程基础设施（CI/门禁/打包） | 4 | 3 | 3 | 4 | 4 | **3.71** | 4.0 | 无覆盖率门槛；无 pre-commit；薄壳待下线 |

## 3. 按架构层

| 层 | 当前分 | 依据 | 目标 |
|---|---:|---|---:|
| 接口层（CLI） | 4 | 统一 `binance-tools` + `python -m` + 旧脚本薄壳三入口；`--help` 冒烟纳入 pytest；错误码 0/1/2 有语义 | 4 |
| 客户端层（HTTP/WS） | 4 | 统一 `client.py`（公开 GET 限频/退避 + 私有签名请求）；签名双语义有官方测试向量；WS 客户端独立模块 | 4 |
| 存储层（SQLite/PG） | 4 | 单写线程 + 有界队列；幂等与并发回归有测试；PG 未进 CI；每事件 commit（批次 5） | 4 |
| 文档层 | 3 | 索引/信念/ADR/计划/质量齐备；`check_docs.py` 机械校验 35+ 链接；缺测试文档与故障演练记录 | 4 |
| 测试与门禁 | 4 | 24 用例 + 六步 `check.sh` + GitHub Actions（`ci`/`docs`）；ruff 零基线；覆盖率门槛待阶段 5 | 4 |

**整体加权（六域平均）≈ 3.40 / 5**。改造目标：阶段 5 结束时 ≥ 3.5，测试与门禁保持 4。

## 4. 复算方式

```bash
# 一键门禁（与 CI 同一脚本）：compileall → ruff → pytest → 文档 → 生成物 → 密钥
bash scripts/gates/check.sh

# 复杂度/重复/密钥（会重写 docs/exec-plans/active/scan/）
python3 scripts/analysis/scan_project.py --root . --out docs/exec-plans/active/scan

# 文档链接/结构/生成物新鲜度
python3 scripts/docs/check_docs.py

# 测试（本地 venv：.venv/bin/python）
.venv/bin/python -m pytest -q
# .venv/bin/python -m pytest --cov=binance_tools --cov-report=term-missing  # 阶段 5 启用

# P0 回归反证：退出码 1 = 未复现（已修复）
python3 scripts/analysis/repro_thread_safety.py; echo "exit=$?"
```

| 指标 | 当前值 | 来源 |
|---|---|---|
| 包版本 / Python 要求 | `binance-tools 0.2.0` / `>=3.10` | `pyproject.toml` |
| 受版本控制文件 / Python 行数 | 以 `git ls-files` 为准（阶段 1 快照见 `scan.json`） | — |
| 最大函数复杂度（近似 CC） | 27（`public.py` cmd_klines） | `scan-report.md`（阶段 1）+ 复核 |
| 跨文件重复窗口 | 批次 2 后应下降（`StreamWriter` 已复用 `MultiSink`） | 重跑扫描器确认 |
| 自动化测试 | 24 用例全过（含并发回归、签名双向量、看门狗） | `pytest -q` |
| ruff 存量违规（基线） | 0（零容忍） | `scripts/gates/ruff_baseline.txt` |
| CI 作业 | 2 个（`ci` / `docs`），公开仓库免费额度 | GitHub Actions |
| 开放 P0 | 0 | `tech-debt-tracker.md` |
| 文档死链 | 0 | `check_docs.py` |

## 5. 评分纪律

- 分数变化必须在提交信息或计划日志中说明原因（修了哪个 TD、加了什么门禁）。
- 不允许"文档分数高但测试为 0"的自我安慰：测试权重 ×2。
- 任何 P0 存在时，所在业务域可靠性最高只能 1 分。
- 门禁基线必须保持为零；新增违规应由门禁拦截而不是加基线。
