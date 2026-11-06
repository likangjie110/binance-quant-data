# 技术债与问题清单（阶段 1 扫描产出）

- 生成日期：2026-11-06
- 扫描范围：仓库内全部受版本控制文件（`work/` 与 `.venv/` 已排除，见 `.gitignore`）
- 原始扫描：`docs/exec-plans/active/scan/scan-report.md`、`scan.json`
- 复现脚本：`scripts/analysis/repro_thread_safety.py`、`scripts/analysis/scan_project.py`
- 字段定义遵循 `docs/HARNESS-RULES.md` 附录 B。

## 一、问题清单

| ID | 标题 | 位置 | 类别 | 严重度 | 证据 | 修复建议 | 业务行为影响 | 关联批次 | 验收方式 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|
| TD-RUNTIME-001 | 多市场监听共享同一个 DB 连接，跨线程写入直接崩溃 | `tools/binance_user_stream.py:762`；`tools/event_sink.py:323,359,364` | 架构 | **P0** | `cmd_listen` 用 `ThreadPoolExecutor(max_workers=len(markets))` 起监听线程，线程内 `writer.write(...)`（`binance_user_stream.py:652,727`）复用主线程 `writer.start()` 时创建的 `SqlSink` 连接。复现：`python3 scripts/analysis/repro_thread_safety.py` → `ProgrammingError: SQLite objects created in a thread can only be used in that same thread` | 单写线程 + 队列（监听线程只入队，`writer` 线程独占连接），或每个监听线程各自持有 sink/连接；`listen` 启动时把 sink 创建放到写线程内 | **修复 bug**（当前 `--sink sqlite/pg` 在多市场实时监听下不可用） | 批次 1 | 复现脚本退出码 0→1 反转；`listen --markets spot,um --sink sqlite` 冒烟 60s 无异常；PG 同场景通过 | 待处理 |
| TD-RUNTIME-002 | 信号引擎跨线程共享可变状态，无锁 | `tools/event_sink.py:553`（`SignalSink.write` 懒加载 `SignalEngine`）、`event_sink.py:447`（`on_event` 更新 positions/realized_pnl） | 架构 | **P0** | 与 TD-RUNTIME-001 同源：多监听线程同时 `write()` → 同一 `SignalEngine` 的 dict 并发读写；无锁、无单线程约束 | 与 TD-RUNTIME-001 一并解决：信号计算收敛到单写线程；或引擎内部加锁并做幂等 key | **修复 bug**（持仓状态/信号可能错乱） | 批次 1 | 两个市场并发灌 1000 条事件，`positions`/信号序列与单线程回放一致（对拍） | 待处理 |
| TD-REL-001 | 无静默流看门狗与优雅关闭 | `tools/binance_user_stream.py:631,700`（while 循环仅看 deadline） | 性能 | P1 | WS 连接可能“握手成功但 0 帧”（合约旧路由即如此），当前无“N 分钟无消息则重连”判断；`KeyboardInterrupt` 只捕获在 `cmd_listen`（:767），工作线程与 WS 连接没有 stop 事件 | 增加 `--idle-timeout`（默认 180s）看门狗；引入 `threading.Event` 停止信号；finally 中关闭 WS 与 sink | 修复 bug（避免假活） | 批次 1 | 人为断流测试：kill 连接后 180s 内自动重连；Ctrl-C 后 5s 内进程退出且无残留连接 | 待处理 |
| TD-REL-002 | 现货监听循环里 `last_ping` 为死变量 | `tools/binance_user_stream.py:629,653` | 复杂度 | P2 | `last_ping = time.time()` 赋值两次，全文无读取（`grep -n last_ping` 仅两处赋值） | 改用 `last_msg_ts` 并接入 TD-REL-001 看门狗 | 无 | 批次 1 | 静态检查无未使用变量；看门狗用例覆盖 | 待处理 |
| TD-ARCH-001 | HTTP/重试/签名逻辑在三个脚本里各写一套 | `tools/binance_pull.py:160`（`get` + 重试/分页，632 行）；`tools/binance_user_stream.py:109,117`（`sign_rest`/`http_json`） | 重复 | P1 | 两套 urllib 封装：头、超时、退避、错误码处理各自实现；`binance_pull` 与 `user_stream` 对 429/418/5xx/TLS 的处理不同（前者 `Retry-After`，后者指数退避） | 抽 `binance_client`（REST 客户端 + 签名 + 统一错误/限频），三脚本复用；行为不变，先对拍 | 无（纯重构） | 批次 2 | 三脚本 selftest 全过；同参数请求的响应/错误码与重构前一致（录制回放对拍） | 待处理 |
| TD-ARCH-002 | `sys.path.insert` 导入同目录模块，运行目录敏感 | `tools/binance_user_stream.py:67` | 架构 | P1 | `sys.path.insert(0, dirname(__file__))` 后 `from event_sink import ...`；从其他 cwd 或用 `python -m` 运行时依赖偶然性 | 改为包结构（`binance_tools/`）+ 相对导入 + `python -m binance_tools.user_stream`；或至少用 `importlib` 显式加载 | 无（纯重构） | 批次 2 | 在 `/tmp` 下用绝对路径运行 `--help`/`selftest` 均通过 | 待处理 |
| TD-ARCH-003 | 无项目元数据：无 `pyproject.toml`，Python 版本与可选依赖未声明 | 仓库根 | 依赖 | P1 | 根目录无 `pyproject.toml`/`requirements.txt`/`setup.py`（`ls` 为空）；代码使用 `str \| None`（需 Python 3.10+，`binance_user_stream.py:117`）；PG 需 `psycopg[binary]`，仅写在文档 | 增加 `pyproject.toml`（requires-python、optional-dependencies: pg/dev）、锁文件或最低版本说明 | 无（工程化） | 批次 2 | `pip install -e .` 成功；`requires-python` 与实际一致 | 待处理 |
| TD-DUP-001 | 两套 fan-out 实现：`StreamWriter` 与 `MultiSink` | `tools/binance_user_stream.py:297`；`tools/event_sink.py:568` | 重复 | P1 | 扫描器命中 2 组 8 行重复窗口（`scan-report.md`）：`user_stream.py:332-333` ↔ `event_sink.py:581-582`，均为 `for s in self.sinks: s.write(n)` + close 容错 | 统一用 `event_sink.MultiSink`，删除 `StreamWriter` 的重复部分（保留控制台打印层） | 无（纯重构） | 批次 2 | 扫描器重复窗口归零；多 sink 自检通过 | 待处理 |
| TD-TEST-001 | 无自动化测试，自检依赖手工运行 | `tools/binance_user_stream.py:391`；`tools/event_sink.py:666`；无 `tests/` | 测试 | P1 | `ls tests` 不存在；两个 `selftest` 是 CLI 子命令，需人记得跑；签名算法有官方向量但未纳入 pytest | 建立 `tests/`：签名向量、事件归一化、sink 幂等、CSV 列、信号状态机；`pytest -q` 一键 | 无（质量） | 批次 3 | `pytest -q` 全绿且覆盖 P0/P1 修复点（含 TD-RUNTIME-001 回归） | 待处理 |
| TD-CI-001 | 无 CI / 无提交门禁 | 无 `.github/workflows/` | 依赖 | P1 | `ls .github/workflows` 不存在；无 pre-commit/husky；门禁仅靠人 | 阶段 3 决策：本地 pre-commit（compileall + pytest + secret scan）优先，CI 平台见 D1 | 无 | 批次 3 | 提交前门禁可本地一键复现；故意引入语法错误会被拦 | 待处理 |
| TD-SEC-001 | 敏感连接串/密钥经命令行参数传递 | `用户数据流接入指南.md:141,259`；`README.md:70`；`tools/binance_user_stream.py:818`（`--pg-dsn` 示例） | 安全 | P1 | 文档与帮助文本鼓励 `--pg-dsn "postgresql://user:pass@..."`：密码会进 shell history 与 `ps` 进程列表；`--key-file` 虽已提供，但 PG 无对应方式 | 支持 `BINANCE_PG_DSN` 环境变量 / `--pg-dsn-file`；文档改为环境变量优先；CI secret 扫描加白名单 | 无（安全加固） | 批次 3 | `ps` 看不到密码；文档示例不再含明文密码 | 待处理 |
| TD-PERF-001 | 每条事件一次 `commit()` + 每条事件一行 `print` | `tools/event_sink.py:425`；`tools/binance_user_stream.py`（51 处 `print`） | 性能 | P2 | 高频行情/成交下 PG 每次 commit 往返；控制台逐条打印放大 I/O 与日志量 | 批量提交（N 条/≤1s）+ `--log-level`/`--quiet`；结构化日志替代 print | 无（性能/可观测性） | 批次 5 | 灌 10k 条事件：PG 写入 P95 提升 ≥3×；默认无逐条刷屏 | 待处理 |
| TD-DUP-002 | DDL 双份：代码内建表与 `sql/` 文件并存 | `tools/event_sink.py:268`；`sql/binance_stream_schema.sql` | 重复 | P2 | 两处 6 张表定义需手工同步；字段/索引改动易漂移 | 以 `sql/*.sql` 为单一事实源，代码读取执行；或反向由代码生成 SQL 文件（CI 校验 diff） | 无（纯重构） | 批次 5 | 修改 schema 只改一处；CI 校验生成物一致 | 待处理 |
| TD-DOC-001 | 规则文档三份并存（两份内容相同） | `docs/HARNESS-RULES.md`；`docs/turn-project-to-harness-rules.md`；`docs/new-project-harness-rules.md` | 文档 | P2 | 前两者 SHA-256 相同（`5d6820b1…`）；`new-project` 不适用于本仓库；易误读/误改 | 收敛：仅保留 `docs/HARNESS-RULES.md`，其余删除或移入归档；记录来源 commit | 无 | 批次 4 | `docs/` 只剩一份规则文档；哈希与上游一致 | 待处理 |
| TD-DOC-002 | README 引用 `work/` 证据，但该目录已 gitignore | `README.md`（17 处 `work/` 引用） | 文档 | P2 | `.gitignore` 含 `work/`（含 435MB asar 解包与逆向 JSON），clone 后 README 中的证据路径全部断链 | 明确证据保留策略：小摘要入库（`docs/evidence/`），大件归档到对象存储/本地快照并写获取方式 | 无 | 批次 4 | clone 后按 README 能复现/获取所有引用证据 | 待处理 |
| TD-DOC-003 | 缺常驻工程文档：`AGENTS.md` / `ARCHITECTURE.md` / `core-beliefs.md` | 仓库根 | 文档 | P2 | 仅有 README/报告/指南；无 agent 常驻契约与架构文档（阶段 2 产出物） | 阶段 2 按附录 E/F 建立三份文档并挂到 README | 无 | 批次 4 | 三份文档存在且链接可达；新会话可按 AGENTS.md 开工 | 待处理 |
| TD-DEP-001 | 依赖版本未锁定 | 文档/`.venv` | 依赖 | P2 | `psycopg 3.3.8` 只出现在文档与本地 venv；无 lock/requirements；上游行为变化不可复现 | `requirements-dev.txt` + `requirements-pg.txt`（或 uv lock），CI 安装用锁定版本 | 无 | 批次 3 | 干净环境按锁定文件可复现 `selftest` | 待处理 |
| TD-CODE-001 | 复杂度热点：长函数/高分支 | `tools/binance_pull.py:317`（93 行/CC≈27）；`tools/binance_user_stream.py:466`（80 行/CC≈20）；`tools/event_sink.py:90`（66 行/CC≈24） | 复杂度 | P2 | `scan-report.md` 复杂度表：三函数分支数 26/19/23，嵌套深度 3–6 | 按职责拆分（参数校验/请求/落盘/打印），配合 TD-ARCH-001 一并重构 | 无（纯重构） | 批次 5 | 拆分后单函数 ≤60 行、CC ≤15；测试全绿 | 待处理 |
| TD-SEC-002 | 密钥扫描器对文档占位符误报 | `scripts/analysis/scan_project.py` | 安全 | P2 | 6 处命中全部是文档示例占位符（`postgresql://user:***@`），无常量忽略名单 → 真阳性淹没 | 增加 `.secretsignore`（路径/正则白名单）并区分代码与文档 | 无（工具） | 批次 3 | 扫描输出 0 误报；人为植入假密钥能命中 | 待处理 |

## 二、P0 复现记录（TD-RUNTIME-001）

```console
$ python3 scripts/analysis/repro_thread_safety.py
临时目录: /var/folders/.../repro-ts-xxxx
复现成功：1 个线程写入抛错
- [spot] ProgrammingError: SQLite objects created in a thread can only be used in that
  same thread. The object was created in thread id ... and this is thread id ...
根因：cmd_listen 的多个监听线程共享同一个 SqlSink 连接
      （sqlite3 连接默认只能创建线程使用；psycopg 连接同样不支持并发使用）。
退出码：0（= 已复现缺陷）
```

> 阶段 1 纪律：只登记、不修复。修复进批次 1，且必须先补回归测试（TD-TEST-001）。

## 三、统计

| 严重度 | 数量 | 说明 |
|---|---:|---|
| P0 | 2 | 阻断 `--sink sqlite/pg` 的实时监听可用性 |
| P1 | 8 | 架构/重复/测试/安全，显著抬升维护成本 |
| P2 | 9 | 文档/性能/整洁度，可排期 |
| 合计 | 19 | — |

> 未发现硬编码真实密钥：扫描命中（8 处）全部是文档/帮助文本里的占位符（如 `postgresql://user:pass@…`），已由 TD-SEC-002 治理误报。`work/`（含 App 配置 AK/SK、Cookie 副本）已被 `.gitignore` 排除，但保留策略待定（TD-DOC-002）。
