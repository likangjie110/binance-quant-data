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

## 2. 按业务域（阶段 3 后）

| 业务域 | 测试 | 文档 | 复杂度 | 依赖方向 | 可靠性 | 加权分 | 目标 | 主要差距 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 公开行情拉取（`binance_pull`） | 1 | 4 | 3 | 4 | 4 | **3.00** | 4.0 | 无分页/限频专项测试；`cmd_klines` 93 行/CC≈27 |
| 私有实时推送（`binance_user_stream`） | 2 | 4 | 2 | 2 | 1 | **2.00** | 4.0 | P0 并发缺陷；签名非 ASCII 缺陷；无 listen 集成测试 |
| 事件落库（`event_sink` sinks） | 3 | 4 | 2 | 3 | 1 | **2.43** | 4.0 | P0 并发缺陷；PG 未进 CI；每事件 commit |
| 策略信号（SignalEngine） | 3 | 3 | 2 | 3 | 1 | **2.29** | 4.0 | 状态无锁（P0 同源）；无长期回放对拍 |
| 数据源逆向证据 | 1 | 4 | 4 | 5 | 3 | **3.00** | 3.5 | 证据依赖本地 `work/`（D3 约定）；无自动复跑校验 |
| 工程基础设施（CI/门禁/打包） | 3 | 3 | 3 | 3 | 3 | **3.00** | 4.0 | ruff 基线未清零；无覆盖率门槛；未包化 |

## 3. 按架构层

| 层 | 当前分 | 依据 | 目标 |
|---|---:|---|---:|
| 接口层（CLI） | 3 | 三个子命令可用、`--help` 冒烟纳入 pytest；错误码 0/1/2 有语义；输出仍耦合 `print`（51 处） | 4 |
| 客户端层（HTTP/WS） | 3 | 签名官方向量纳入测试（ASCII 通过，非 ASCII 以 xfail 记录 TD-SIGN-001）；WS 自研客户端实测通过；HTTP/重试仍三套重复 | 4 |
| 存储层（SQLite/PG） | 3 | 幂等与计数有测试；PG 未进 CI；单写线程缺陷（P0）未修；每事件 commit | 4 |
| 文档层 | 3 | 索引/信念/ADR/计划/质量齐备；`check_docs.py` 机械校验 35 条链接；缺测试文档与故障演练记录 | 4 |
| 测试与门禁 | 3 | 20 用例 + 六步 `check.sh` + GitHub Actions（`ci`/`docs`）；覆盖率与 P0 回归未转正 | 4 |

**整体加权（六域平均）≈ 2.62 / 5**。改造目标：阶段 5 结束时 ≥ 3.5，P0 清零，测试与门禁 ≥ 3。

## 4. 复算方式

```bash
# 一键门禁（与 CI 同一脚本）：compileall → ruff 基线 → pytest → 文档 → 生成物 → 密钥
bash scripts/gates/check.sh

# 复杂度/重复/密钥（会重写 docs/exec-plans/active/scan/）
python3 scripts/analysis/scan_project.py --root . --out docs/exec-plans/active/scan

# 文档链接/结构/生成物新鲜度
python3 scripts/docs/check_docs.py

# 测试（本地 venv：.venv/bin/python）
.venv/bin/python -m pytest -q
# .venv/bin/python -m pytest --cov=binance_tools --cov-report=term-missing  # 包化后启用

# 已知 P0 是否仍存在（0=存在缺陷，1=已修复）
python3 scripts/analysis/repro_thread_safety.py; echo "exit=$?"
```

| 指标 | 当前值 | 来源 |
|---|---|---|
| 受版本控制文件 / Python 行数 | 15 / 2,643（阶段 1 扫描时；后续新增文档/脚本后不再等同） | `scan.json` summary |
| 最大函数复杂度（近似 CC） | 27（`binance_pull.py:317`） | `scan-report.md` |
| 跨文件重复窗口 | 2 组 | `scan-report.md` |
| 自动化测试 | 20 用例（18 passed + 2 xfailed） | `pytest -q` |
| ruff 存量违规（基线） | 5（只拦新增） | `scripts/gates/ruff_baseline.txt` |
| CI 作业 | 2 个（`ci` / `docs`），公开仓库免费额度 | GitHub Actions |
| 开放 P0 | 2 | `tech-debt-tracker.md` |
| 文档死链 | 0 | `check_docs.py` |

## 5. 评分纪律

- 分数变化必须在提交信息或计划日志中说明原因（修了哪个 TD、加了什么门禁）。
- 不允许"文档分数高但测试为 0"的自我安慰：测试权重 ×2。
- 任何 P0 存在时，所在业务域可靠性最高只能 1 分。
- 门禁基线（ruff 5 条）必须在批次 1/2 清零；基线长期残留视为质量倒退。
