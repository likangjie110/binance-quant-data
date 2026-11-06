# 外部参考索引

> 只放"会反复查"的外部资料；本地快照缺失时回源。

## 币安官方

| 主题 | 链接 | 用途 |
|---|---|---|
| 现货 REST（含用户数据流说明） | https://developers.binance.com/docs/binance-spot-api-docs | API 路径、错误码、限频表 |
| 现货 WebSocket 流 | https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams | 公共流命名、订阅格式 |
| 现货 WebSocket API | https://developers.binance.com/docs/binance-spot-api-docs/web-socket-api | `userDataStream.subscribe.signature` 签名规则 |
| 现货用户数据流 | https://developers.binance.com/docs/binance-spot-api-docs/user-data-stream | 事件字段 |
| U 本位 Connect / 路由迁移公告 | https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Connect | `/public` `/market` `/private`、订阅上限 |
| 路由迁移公告（原文） | https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Important-WebSocket-Change-Notice | 旧 URL 停用时间与行为 |
| 币本位 Connect | https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/websocket-market-streams/Connect | dstream 流 |
| 期权 Connect | https://developers.binance.com/en/docs/products/derivatives-trading-options/websocket-market-streams/Connect | eapi 流 |
| 历史数据仓库 | https://data.binance.vision | 日/月 zip + `.CHECKSUM` |
| 历史数据说明 | https://github.com/binance/binance-public-data | 路径规则、时间戳单位差异 |

## 本地快照（`work/`，不入库，D3）

| 路径 | 内容 |
|---|---|
| `work/ws/docs_raw/` | 官方文档 Markdown 快照（现货 REST/WS、合约 Connect、期权、迁移公告） |
| `work/evidence/` | 桌面端 bootstrap 原始响应（dynamic-config / dynamic-domain / rate_limits） |
| `work/verify/` | REST 端点的 108 次探针结果与样例输出 |
| `work/rea/` | REA 分析证据与端点节点导出 |

> `work/` 只在本机存在；需要时按 `work/README` 缺失的情况下用根目录报告与脚本复现。

## 上游方法论

| 仓库 | 用途 |
|---|---|
| `Tairraos/harness-go`（本地镜像 `~/references/harness-go`） | 本次改造规则来源（`docs/HARNESS-RULES.md`） |
| `deepseek-ai/dsh-superagent-prototype`（本地镜像 `~/references/dsh-superagent-prototype`） | 授权/幂等/恢复机制参考 |
