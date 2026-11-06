# 产品规格索引

> 本项目是**本地只读数据工具箱**，不是交易系统。以下三项能力即全部对外承诺。
> 每项含范围、非目标与可验收标准；详细操作见对应指南。

## 能力 1：公开行情拉取（`tools/binance_pull.py`）

| 项 | 内容 |
|---|---|
| 用户故事 | 作为量化研究者，我想按市场/交易对/周期拉 K 线、ticker、盘口与交易规则，落到 CSV 供回测。 |
| 范围 | 现货 `api/v3`、U 本位 `fapi/v1`、币本位 `dapi/v1`、期权 `eapi/v1`；K 线分页、24h ticker、depth、exchangeInfo、期权合约清单。 |
| 非目标 | 不下单、不查账户、不做实时推送、不做回测引擎。 |
| 验收 | 四个市场各拉一次 K 线成功；`--start/--end` 分页无重复且时间递增；期权用合法合约；限频接近上限时自动让路；退出码语义正确（0/1/2）。 |
| 指南 | `用户数据流接入指南.md` 与 `work/verify/verify_report.md`（实测证据） |

## 能力 2：私有实时推送（`tools/binance_user_stream.py`）

| 项 | 内容 |
|---|---|
| 用户故事 | 作为有币安账户的用户，我想用只读 API Key 实时收到自己的订单/成交/余额/持仓事件。 |
| 范围 | 现货 WS API 签名订阅；U 本位/币本位 listenKey + 私有 WS；`selftest`（无密钥）、`check`（权限校验）、`snapshot`（余额/持仓/挂单快照）、`listen`（JSONL）。 |
| 非目标 | 不提取 App 登录态（ADR-001）；不做下单；不做 GUI。 |
| 验收 | `selftest` 通过；`check` 能区分 -2014/-2015/-1022 并给出处理建议；`listen` 单市场/多市场均能收事件；断线重连与 listenKey 续期；私有数据不打印密钥。 |
| 指南 | `用户数据流接入指南.md` |

## 能力 3：事件落库与策略信号（`tools/event_sink.py`）

| 项 | 内容 |
|---|---|
| 用户故事 | 作为策略开发者，我想把实时事件落到 SQLite/PostgreSQL 并得到订单/持仓/PNL 信号，供下次决策使用。 |
| 范围 | 归一化三类市场事件；JSONL/CSV/SQLite/PG 四类 sink；orders upsert、fills 去重、events 追加；信号：ORDER_*/FILL/POSITION_*/PNL_REALIZED/BALANCE_CHANGED。 |
| 非目标 | 不做撮合、不做风控强制平仓、不替用户决定策略。 |
| 验收 | `event_sink.py selftest` 三后端计数正确；重复写入幂等；`replay` 可从 JSONL 重算同序信号；PG 表结构与 `sql/binance_stream_schema.sql` 一致。 |
| 已知限制 | 多市场并发写库在批次 1 前不可用（TD-RUNTIME-001）。 |

## 全局非目标

- 不提供交易执行、资金划转、提币能力。
- 不保证数据实时性/完整性 SLA；币安接口变更需跟随（见 `docs/RELIABILITY.md` 与 `TROUBLESHOOTING.md`）。
- 不采集/上传任何用户私有数据到第三方。
