# 文档索引

> 本文件索引仓库内全部文档，并标注校验状态。新增/删除文档必须同步更新本索引（`check_docs.py` 会拦截遗漏）。
>
> 校验状态取值：**已校验**（与代码/计划交叉核对过，含日期）、**自动生成**（禁止手改）、**上游快照**（外部规则原文）、**待核实**（需开 issue 跟踪）。

## 0. 入口

| 文档 | 说明 | 校验状态 |
|---|---|---|
| [README.md](../README.md) | 项目入口、快速开始、当前阶段 | 已校验 2026-11-06 |
| [AGENTS.md](../AGENTS.md) | 智能体入口地图（≤100 行） | 已校验 2026-11-06 |
| [ARCHITECTURE.md](../ARCHITECTURE.md) | 领域地图、依赖方向规则、目标包结构 | 已校验 2026-11-06（抽样 4 处与代码一致） |
| [docs/HARNESS-RULES.md](HARNESS-RULES.md) | 存量项目 harness 改造规则（上游原文，不手改） | 上游快照（SHA-256 `5d6820b1…`） |

## 1. 设计与信念

| 文档 | 说明 | 校验状态 |
|---|---|---|
| [design-docs/index.md](design-docs/index.md) | 设计文档索引 | 已校验 2026-11-06 |
| [design-docs/core-beliefs.md](design-docs/core-beliefs.md) | 第一性原则与裁决依据 | 已校验 2026-11-06 |
| [design-docs/decisions.md](design-docs/decisions.md) | ADR-001 ~ ADR-008 | 已校验 2026-11-06 |

## 2. 产品与能力

| 文档 | 说明 | 校验状态 |
|---|---|---|
| [product-specs/index.md](product-specs/index.md) | 三项能力（公开行情/私有推送/落库信号）范围与验收 | 已校验 2026-11-06 |
| [币安数据源分析报告.md](../币安数据源分析报告.md) | REA 逆向结论：数据源来自哪里、能否自取 | 已校验 2026-11-06（含实测证据） |
| [用户数据流接入指南.md](../用户数据流接入指南.md) | API Key、三条私有通道、落库与信号操作指南 | 已校验 2026-11-06 |

## 3. 计划与台账

| 文档 | 说明 | 校验状态 |
|---|---|---|
| [exec-plans/active/harness-migration.md](exec-plans/active/harness-migration.md) | 进行中的改造计划（状态、批次、决策、日志） | 已校验 2026-11-06 |
| [exec-plans/tech-debt-tracker.md](exec-plans/tech-debt-tracker.md) | 技术债台账（19 项，含 P0 复现证据） | 已校验 2026-11-06 |
| [exec-plans/completed/README.md](exec-plans/completed/README.md) | 已完成计划归档规则（当前为空） | 已校验 2026-11-06 |
| [exec-plans/active/scan/scan-report.md](exec-plans/active/scan/scan-report.md) | **阶段 1 扫描快照**（历史证据，非当前状态） | 自动生成于 `474e382`（`scripts/analysis/scan_project.py`） |
| [exec-plans/active/scan/scan.json](exec-plans/active/scan/scan.json) | 扫描原始数据（机器可读） | 自动生成 |

## 4. 工程与质量

| 文档 | 说明 | 校验状态 |
|---|---|---|
| [DEVELOPMENT.md](DEVELOPMENT.md) | 环境、运行、测试、调试、提交、发布、文档工作流 | 已校验 2026-11-06 |
| [QUALITY_SCORE.md](QUALITY_SCORE.md) | 按业务域/架构层评分与差距、复算命令 | 已校验 2026-11-06 |
| [CI.md](CI.md) | 框架判定、现有 CI、门禁计划 | 已校验 2026-11-06 |
| [RELIABILITY.md](RELIABILITY.md) | 可靠性目标、失败模式、重试策略、运行手册 | 已校验 2026-11-06 |
| [SECURITY.md](SECURITY.md) | 资产分级、密钥与私有数据规则、事件响应 | 已校验 2026-11-06 |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 症状 → 根因 → 动作（鉴权/流/限频/格式/落库/网络） | 已校验 2026-11-06 |

## 5. 生成物与参考

| 文档 | 说明 | 校验状态 |
|---|---|---|
| [generated/db-schema.md](generated/db-schema.md) | 6 张表结构（由 `sql/` 生成） | 自动生成（`scripts/docs/gen_db_schema.py --check` 校验） |
| [references/index.md](references/index.md) | 币安官方文档链接 + 本地快照位置（`work/` 不入库） | 已校验 2026-11-06 |

## 维护规则

1. **新增文档**：放到对应目录 + 在本索引加一行 + 写校验状态；`check_docs.py` 会验证索引完整性。
2. **删除文档**：先从索引移除，再删文件；被引用的链接一起改（校验器会抓死链）。
3. **`work/` 下的本地证据不进入本索引**（D3：本地保留、不入库），由 [references/index.md](references/index.md) 统一说明位置。
4. **自动生成物禁止手改**；改事实源（`sql/`、扫描器）后重跑生成器。
