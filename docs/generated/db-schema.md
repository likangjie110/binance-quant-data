# 数据库表结构（自动生成）

> ⚠️ **本文件由脚本生成，禁止手改**。
> 事实源：`sql/binance_stream_schema.sql`；生成命令：`python3 scripts/docs/gen_db_schema.py`。
> CI 会校验本文件与事实源一致（`gen_db_schema.py --check`）。

共 6 张表。

## `stream_events`

| 列 | 类型 | 主键 |
|---|---|---|
| `id` | `BIGSERIAL` | ✓ |
| `ts` | `TIMESTAMPTZ NOT NULL` |  |
| `market` | `TEXT NOT NULL` |  |
| `event_type` | `TEXT NOT NULL` |  |
| `symbol` | `TEXT` |  |
| `raw` | `JSONB NOT NULL` |  |

主键：`(id)`

## `orders`

| 列 | 类型 | 主键 |
|---|---|---|
| `market` | `TEXT NOT NULL` | ✓ |
| `order_id` | `BIGINT NOT NULL` | ✓ |
| `symbol` | `TEXT` |  |
| `client_order_id` | `TEXT` |  |
| `side` | `TEXT` |  |
| `order_type` | `TEXT` |  |
| `status` | `TEXT` |  |
| `price` | `NUMERIC` |  |
| `orig_qty` | `NUMERIC` |  |
| `executed_qty` | `NUMERIC` |  |
| `avg_price` | `NUMERIC` |  |
| `cum_quote` | `NUMERIC` |  |
| `last_qty` | `NUMERIC` |  |
| `last_price` | `NUMERIC` |  |
| `realized_pnl` | `NUMERIC` |  |
| `is_maker` | `BOOLEAN` |  |
| `event_time` | `TIMESTAMPTZ` |  |
| `updated_at` | `TIMESTAMPTZ` |  |
| `raw` | `JSONB` |  |

主键：`(market, order_id)`

## `fills`

| 列 | 类型 | 主键 |
|---|---|---|
| `market` | `TEXT NOT NULL` | ✓ |
| `order_id` | `BIGINT NOT NULL` | ✓ |
| `trade_id` | `BIGINT` | ✓ |
| `symbol` | `TEXT` |  |
| `side` | `TEXT` |  |
| `price` | `NUMERIC` |  |
| `qty` | `NUMERIC` |  |
| `quote_qty` | `NUMERIC` |  |
| `commission` | `NUMERIC` |  |
| `commission_asset` | `TEXT` |  |
| `is_maker` | `BOOLEAN` |  |
| `realized_pnl` | `NUMERIC` |  |
| `trade_time` | `TIMESTAMPTZ NOT NULL` | ✓ |

主键：`(market, order_id, trade_id, trade_time)`

## `balances`

| 列 | 类型 | 主键 |
|---|---|---|
| `market` | `TEXT NOT NULL` | ✓ |
| `asset` | `TEXT NOT NULL` | ✓ |
| `free` | `NUMERIC` |  |
| `locked` | `NUMERIC` |  |
| `updated_at` | `TIMESTAMPTZ` |  |

主键：`(market, asset)`

## `positions`

| 列 | 类型 | 主键 |
|---|---|---|
| `market` | `TEXT NOT NULL` | ✓ |
| `symbol` | `TEXT NOT NULL` | ✓ |
| `position_amt` | `NUMERIC` |  |
| `entry_price` | `NUMERIC` |  |
| `unrealized_pnl` | `NUMERIC` |  |
| `updated_at` | `TIMESTAMPTZ` |  |

主键：`(market, symbol)`

## `account_snapshots`

| 列 | 类型 | 主键 |
|---|---|---|
| `id` | `BIGSERIAL` | ✓ |
| `ts` | `TIMESTAMPTZ` |  |
| `market` | `TEXT` |  |
| `kind` | `TEXT` |  |
| `payload` | `JSONB` |  |

主键：`(id)`

## 索引

| 索引 | 表 | 列 |
|---|---|---|
| `idx_stream_events_ts` | `stream_events` | `ts` |
| `idx_stream_events_type` | `stream_events` | `market, event_type` |
