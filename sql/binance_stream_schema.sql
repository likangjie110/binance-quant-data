-- 币安用户数据流落库表结构（PostgreSQL 14+）
-- 由 tools/event_sink.py 自动创建；此文件供 DBA/手工建表使用。
-- 用法：psql "$PG_DSN" -f sql/binance_stream_schema.sql

CREATE TABLE IF NOT EXISTS stream_events (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL,
  market TEXT NOT NULL,          -- spot / um / cm
  event_type TEXT NOT NULL,      -- executionReport / ORDER_TRADE_UPDATE / ACCOUNT_UPDATE ...
  symbol TEXT,
  raw JSONB NOT NULL             -- 原始事件（权威数据，回放/补字段都靠它）
);
CREATE INDEX IF NOT EXISTS idx_stream_events_ts ON stream_events(ts);
CREATE INDEX IF NOT EXISTS idx_stream_events_type ON stream_events(market, event_type);

CREATE TABLE IF NOT EXISTS orders (
  market TEXT NOT NULL,
  order_id BIGINT NOT NULL,
  symbol TEXT,
  client_order_id TEXT,
  side TEXT,
  order_type TEXT,
  status TEXT,                   -- NEW / PARTIALLY_FILLED / FILLED / CANCELED / EXPIRED / REJECTED
  price NUMERIC,
  orig_qty NUMERIC,
  executed_qty NUMERIC,
  avg_price NUMERIC,
  cum_quote NUMERIC,
  last_qty NUMERIC,
  last_price NUMERIC,
  realized_pnl NUMERIC,
  is_maker BOOLEAN,
  event_time TIMESTAMPTZ,
  updated_at TIMESTAMPTZ,
  raw JSONB,
  PRIMARY KEY (market, order_id)
);

CREATE TABLE IF NOT EXISTS fills (
  market TEXT NOT NULL,
  order_id BIGINT NOT NULL,
  trade_id BIGINT,
  symbol TEXT,
  side TEXT,
  price NUMERIC,
  qty NUMERIC,
  quote_qty NUMERIC,
  commission NUMERIC,
  commission_asset TEXT,
  is_maker BOOLEAN,
  realized_pnl NUMERIC,
  trade_time TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (market, order_id, trade_id, trade_time)
);

CREATE TABLE IF NOT EXISTS balances (
  market TEXT NOT NULL,
  asset TEXT NOT NULL,
  free NUMERIC,
  locked NUMERIC,
  updated_at TIMESTAMPTZ,
  PRIMARY KEY (market, asset)
);

CREATE TABLE IF NOT EXISTS positions (
  market TEXT NOT NULL,
  symbol TEXT NOT NULL,
  position_amt NUMERIC,
  entry_price NUMERIC,
  unrealized_pnl NUMERIC,
  updated_at TIMESTAMPTZ,
  PRIMARY KEY (market, symbol)
);

CREATE TABLE IF NOT EXISTS account_snapshots (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ,
  market TEXT,
  kind TEXT,                     -- ACCOUNT_UPDATE / BALANCE
  payload JSONB
);

-- 常用查询
-- 当前持仓（非零）：
--   SELECT market, symbol, position_amt, entry_price, unrealized_pnl
--   FROM positions WHERE position_amt <> 0 ORDER BY market, symbol;
-- 最近 20 条成交：
--   SELECT trade_time, market, symbol, side, price, qty, realized_pnl, commission_asset
--   FROM fills ORDER BY trade_time DESC LIMIT 20;
-- 当日已实现盈亏：
--   SELECT market, symbol, SUM(realized_pnl) FROM fills
--   WHERE trade_time >= date_trunc('day', now()) GROUP BY 1,2;
