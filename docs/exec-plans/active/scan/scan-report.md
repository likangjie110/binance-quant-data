# 项目扫描报告（阶段 1 · 只读）

- 生成时间：2026-11-06T15:28:04Z
- 根目录：`/Users/likangjie/项目代码/量化数据源`
- 文件 15 个（.py 5 个），Python 代码 2643 行，全量 6917 行
- 函数 112 个；跨文件重复窗口 2 组；疑似密钥/凭证 8 处；TODO/FIXME 0 处

## 文件清单（按 LOC 降序）

| 文件 | 行数 | 字节 |
|---|---:|---:|
| `docs/HARNESS-RULES.md` | 1101 | 73064 |
| `docs/turn-project-to-harness-rules.md` | 1101 | 73064 |
| `docs/new-project-harness-rules.md` | 871 | 54079 |
| `tools/binance_user_stream.py` | 834 | 36212 |
| `tools/event_sink.py` | 793 | 35481 |
| `tools/binance_pull.py` | 632 | 29202 |
| `币安数据源分析报告.md` | 418 | 25692 |
| `scripts/analysis/scan_project.py` | 317 | 12252 |
| `用户数据流接入指南.md` | 263 | 13343 |
| `docs/exec-plans/active/harness-migration.md` | 217 | 14632 |
| `README.md` | 94 | 5217 |
| `sql/binance_stream_schema.sql` | 92 | 2729 |
| `scripts/analysis/repro_thread_safety.py` | 67 | 2540 |
| `docs/CI.md` | 60 | 2979 |
| `docs/exec-plans/tech-debt-tracker.md` | 57 | 11683 |

## 复杂度热点：最长函数

| 文件:行 | 函数 | 长度 | 分支 | 近似圈复杂度 | 嵌套深度 |
|---|---|---:|---:|---:|---:|
| `scripts/analysis/scan_project.py:150` | `main` | 164 | 36 | 37 | 5 |
| `tools/binance_pull.py:317` | `cmd_klines` | 93 | 26 | 27 | 3 |
| `tools/binance_user_stream.py:466` | `cmd_check` | 80 | 19 | 20 | 4 |
| `tools/event_sink.py:666` | `cmd_selftest` | 78 | 21 | 22 | 5 |
| `tools/binance_user_stream.py:663` | `_futures_listen` | 72 | 21 | 22 | 5 |
| `tools/binance_pull.py:160` | `get` | 71 | 18 | 19 | 4 |
| `tools/binance_user_stream.py:391` | `cmd_selftest` | 70 | 12 | 13 | 3 |
| `tools/event_sink.py:90` | `normalize` | 66 | 23 | 24 | 6 |
| `tools/event_sink.py:364` | `write` | 62 | 8 | 9 | 1 |
| `tools/binance_user_stream.py:551` | `cmd_snapshot` | 61 | 8 | 9 | 2 |
| `tools/event_sink.py:447` | `on_event` | 54 | 18 | 19 | 5 |
| `tools/binance_user_stream.py:164` | `__init__` | 49 | 10 | 11 | 2 |
| `tools/binance_pull.py:551` | `build_parser` | 48 | 2 | 3 | 2 |
| `tools/binance_user_stream.py:737` | `cmd_listen` | 47 | 11 | 12 | 6 |
| `scripts/analysis/scan_project.py:64` | `scan_python` | 46 | 13 | 14 | 2 |

## 复杂度热点：分支最多

| 文件:行 | 函数 | 长度 | 分支 | 近似圈复杂度 |
|---|---|---:|---:|---:|
| `scripts/analysis/scan_project.py:150` | `main` | 164 | 36 | 37 |
| `tools/binance_pull.py:317` | `cmd_klines` | 93 | 26 | 27 |
| `tools/event_sink.py:90` | `normalize` | 66 | 23 | 24 |
| `tools/binance_user_stream.py:663` | `_futures_listen` | 72 | 21 | 22 |
| `tools/event_sink.py:666` | `cmd_selftest` | 78 | 21 | 22 |
| `tools/binance_user_stream.py:466` | `cmd_check` | 80 | 19 | 20 |
| `tools/binance_pull.py:160` | `get` | 71 | 18 | 19 |
| `tools/event_sink.py:447` | `on_event` | 54 | 18 | 19 |
| `tools/binance_pull.py:488` | `cmd_symbols` | 41 | 14 | 15 |
| `scripts/analysis/scan_project.py:64` | `scan_python` | 46 | 13 | 14 |
| `tools/binance_user_stream.py:617` | `_spot_listen` | 44 | 13 | 14 |
| `tools/binance_user_stream.py:391` | `cmd_selftest` | 70 | 12 | 13 |
| `tools/binance_user_stream.py:117` | `http_json` | 41 | 11 | 12 |
| `tools/binance_user_stream.py:737` | `cmd_listen` | 47 | 11 | 12 |
| `tools/binance_user_stream.py:243` | `recv` | 37 | 11 | 12 |

## 跨文件重复代码（8 行窗口）

- `ace72accce7ba983` → `/Users/likangjie/项目代码/量化数据源/tools/binance_user_stream.py`, `/Users/likangjie/项目代码/量化数据源/tools/event_sink.py`
  - 位置：/Users/likangjie/项目代码/量化数据源/tools/binance_user_stream.py:332, /Users/likangjie/项目代码/量化数据源/tools/event_sink.py:581
- `cd37aa97a43c0e7d` → `/Users/likangjie/项目代码/量化数据源/tools/binance_user_stream.py`, `/Users/likangjie/项目代码/量化数据源/tools/event_sink.py`
  - 位置：/Users/likangjie/项目代码/量化数据源/tools/binance_user_stream.py:333, /Users/likangjie/项目代码/量化数据源/tools/event_sink.py:582

## 本地模块依赖

- `scripts/analysis/repro_thread_safety.py` → `event_sink`
- `scripts/analysis/repro_thread_safety.py` → `binance_user_stream`
- `tools/binance_user_stream.py` → `event_sink`

## 第三方依赖（import 统计）

- `urllib` × 6
- `os` × 5
- `sys` × 5
- `__future__` × 4
- `argparse` × 4
- `json` × 4
- `datetime` × 4
- `time` × 3
- `psycopg` × 3
- `tempfile` × 2
- `concurrent` × 2
- `hashlib` × 2
- `csv` × 2
- `random` × 2
- `socket` × 2
- `ssl` × 2
- `traceback` × 1
- `ast` × 1
- `re` × 1
- `collections` × 1
- `base64` × 1
- `hmac` × 1
- `struct` × 1
- `uuid` × 1
- `sqlite3` × 1

## 疑似密钥/凭证（已脱敏）

- `README.md:70` [pg_url_with_password] `postgresql://user:***@`
- `docs/exec-plans/tech-debt-tracker.md:23` [pg_url_with_password] `postgresql://user:***@`
- `docs/exec-plans/tech-debt-tracker.md:31` [pg_url_with_password] `postgresql://user:***@`
- `tools/binance_user_stream.py:818` [pg_url_with_password] `postgresql://user:***@`
- `tools/event_sink.py:12` [pg_url_with_password] `postgresql://user:***@`
- `tools/event_sink.py:26` [pg_url_with_password] `postgresql://postgres:***@`
- `用户数据流接入指南.md:141` [pg_url_with_password] `postgresql://user:***@`
- `用户数据流接入指南.md:259` [pg_url_with_password] `postgresql://user:***@`

## TODO / FIXME

未发现。
