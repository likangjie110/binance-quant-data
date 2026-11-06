# 设计决策记录（ADR）

> 记录"为什么这样做"，而不是"是什么"。每条含背景、决策、后果与证据链接。
> 新决策追加编号；被推翻时保留原文并标注 Superseded。

## ADR-001 用官方 API Key 用户数据流，不复刻 App 私有通道

- **日期**：2026-11-06
- **背景**：用户已登录币安桌面端，希望直接用当前会话拿私有实时推送。实测：登录态不在可直读 Cookie 中
  （默认库 24 条均非鉴权；`internal-browser` 分区只有 UI 偏好；`desktop.db.users` 为 0 行）；
  App 私有流是 `ws-token` + gzip + `GET_PROPERTY` 私有协议，且 `sfstream/nbstream` 对外部返回 1006/302。
- **决策**：走官方「API Key → 用户数据流」（现货 WS API 签名订阅；合约 listenKey），不提取/复用 App 会话。
- **后果**：需要用户创建只读 API Key；换来稳定、文档化、可长期运行的私有推送；不触碰 ToS 灰色区。
- **证据**：`用户数据流接入指南.md`；`tools/binance_user_stream.py`；`docs/RELIABILITY.md`。

## ADR-002 现货用户流走 WS API `userDataStream.subscribe.signature`

- **日期**：2026-11-06
- **背景**：旧 `POST /api/v3/userDataStream` 实测返回 **410 Gone**；官方文档改为 WS API 订阅，
  `userDataStream.subscribe` 需 Ed25519 登录会话，`userDataStream.subscribe.signature` 支持 HMAC 签名。
- **决策**：连接 `wss://ws-api.binance.com:443/ws-api/v3`，用 HMAC-SHA256（参数按名排序）签名订阅；
  签名算法用官方测试向量自检（`aa1b5712…`）。
- **后果**：不依赖 Ed25519；订阅随连接存在，重连需重新订阅；单连接最多 1000 活跃订阅。
- **证据**：`tools/binance_user_stream.py:109`（`sign_rest`）、`:391`（selftest 向量）。

## ADR-003 合约 WS 必须使用 `/market`、`/public`、`/private` 路由

- **日期**：2026-11-06
- **背景**：实测 `wss://fstream.binance.com/ws/btcusdt@aggTrade` 握手 101 但 0 帧；官方
  *Important WebSocket Change Notice* 明确旧路径只保留 `/public` 数据，行情在 `/market`、用户流在 `/private`，
  旧 URL 计划 2026-04-23 停用。
- **决策**：行情用 `/market/ws`（或 `/market/stream?streams=`），盘口用 `/public/ws`，用户数据用 `/private/ws?listenKey=`。
- **后果**：代码内保留旧路径兜底但不得作为默认；文档与测试以新路由为准。
- **证据**：`work/ws/ws_report.md`（实测矩阵）、`tools/binance_user_stream.py` 的 URL 常量。

## ADR-004 落库双写：SQLite（本地）+ PostgreSQL（服务端）

- **日期**：2026-11-06；决策人：用户（D4）
- **背景**：本地研究需要零依赖、可回放；生产/多策略共享需要并发与查询能力。
- **决策**：sink 层同时支持 `sqlite` 与 `pg`；默认组合 `jsonl,csv,sqlite`，生产再加 `pg`；
  两者共用同一套归一化事件与表语义（6 张表）。
- **后果**：写入路径必须单写线程（TD-RUNTIME-001），否则两个后端都会崩；PG 走可选依赖。
- **证据**：`tools/event_sink.py`；`sql/binance_stream_schema.sql`；`docs/generated/db-schema.md`。

## ADR-005 包化（pyproject + `binance_tools/`）

- **日期**：2026-11-06；决策人：用户（D2）
- **背景**：三个脚本各自实现 HTTP/重试/配置；`sys.path` 注入导入；无依赖声明与 Python 版本约束。
- **决策**：批次 2 收敛为 `binance_tools/` 包 + `pyproject.toml` + `console_scripts: binance-tools`；
  `tools/*.py` 保留薄壳保证旧命令可用。
- **后果**：迁移期双入口并存；CLI 行为与输出格式不变（先对拍后切换）；`tests/` 可导入包内模块。
- **证据**：`ARCHITECTURE.md` §3；`docs/exec-plans/active/harness-migration.md` 批次 2。

## ADR-006 CI 采用 GitHub Actions

- **日期**：2026-11-06；决策人：用户（D1）
- **背景**：仓库无 CI、无门禁；阶段 2 需要文档校验作业，阶段 3 需要完整质量门禁。
- **决策**：使用 GitHub Actions；阶段 2 先落 `docs.yml`（文档校验），阶段 3 扩展 `ci.yml`（compileall +
  pytest + 密钥扫描 + 依赖锁定安装）。
- **后果**：需要仓库推到 GitHub 并配置分支保护；CI 失败必须能本地复现（同一脚本）。
- **证据**：`.github/workflows/docs.yml`；`scripts/docs/check_docs.py`；`docs/CI.md`。

## ADR-007 `work/` 证据本地保留、不进版本库

- **日期**：2026-11-06；决策人：用户（D3）
- **背景**：`work/` 约 1GB（asar 解包、REA JSON、bootstrap 配置、Cookie 副本），含 App 配置 AK/SK 等敏感物。
- **决策**：正常保留在本地磁盘，`.gitignore` 排除；README/文档说明其性质与再生成方式（脚本可复跑）；
  仓库只保留小型摘要（`docs/exec-plans/active/scan/`）。
- **后果**：clone 后部分证据路径不可达，但可复现；敏感物不出本机。
- **证据**：`.gitignore`；`README.md`；TD-DOC-002（已豁免）。

## ADR-008 改造采用 `harnessing` 分支 + 批次制

- **日期**：2026-11-06
- **背景**：存量项目需在不破坏现有可用性的前提下逐步 harness 化；阶段 1 计划需可回滚。
- **决策**：`main` 保存基线（`07cae02`），改造在 `harnessing` 分支按批次（可靠性 → 包化 → 门禁 → 文档 → 性能）
  推进；每批独立提交与回滚方案。
- **后果**：阶段 4 前业务代码零改动；批次 1 是唯一改变运行时行为的批次（bug 修复）。
- **证据**：`docs/exec-plans/active/harness-migration.md` §4；`git log --oneline`。
