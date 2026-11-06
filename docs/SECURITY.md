# 安全说明

> 本项目是本机只读工具，没有服务端。安全边界主要是：**密钥不外泄、私有数据不出版本库/本机、代码不具备资金操作能力**。

## 1. 资产与敏感级别

| 资产 | 位置 | 级别 | 处理规则 |
|---|---|---|---|
| 币安 API Key/Secret | 环境变量 `BINANCE_API_KEY/SECRET` 或 `--key-file` | **极高** | 只读权限；不打印（输出掩码）；不写日志；不提交 |
| PostgreSQL DSN（含密码） | `--pg-dsn` / 环境变量（建议） | 高 | 当前经命令行传入会进 shell history 与 `ps`（TD-SEC-001，批次 3 修） |
| 用户私有事件（订单/余额/持仓） | `work/private/`、`work/signals/` | 高 | 已 gitignore；不提交、不外传 |
| 桌面端逆向证据（含 App 配置 AK/SK、Cookie 副本） | `work/` | 高 | D3：本地正常保留，不入库；不复制到聊天/第三方 |
| 公共行情数据 | `work/verify/data/` 等 | 低 | 可公开 |

## 2. 代码层面的安全约束

1. **只读**：全仓库无下单/撤单/划转/提币调用；评审与后续 CI 用关键字扫描强制。
2. **密钥只进不出**：`binance_user_stream.py` 对 Key 输出做掩码；错误信息不拼接 secret。
3. **最小权限**：创建 API Key 时只勾"允许读取"；如需合约，单独勾合约读取；配置 IP 白名单。
4. **可选依赖隔离**：PostgreSQL 只在 `.venv`（或用户自选环境）安装 `psycopg[binary]`，不污染系统 Python。
5. **不引入第三方数据上报**：无遥测、无 SDK；所有网络请求目标为币安域名。

## 3. 版本库卫生

`.gitignore` 已排除：

```
work/            # 逆向证据 + 私有数据（含 AK/SK、Cookie 副本）
work/private/    # 账户快照、私有事件
work/signals/    # 信号与回放
.venv/           # 本地依赖
*key*.txt  .env  # 密钥文件
```

提交前自查：`git status --short` 不得出现上述路径；`python3 scripts/analysis/scan_project.py` 的
"疑似密钥"一栏只能是文档占位符（TD-SEC-002 治理误报）。

## 4. 威胁模型（简化）

| 威胁 | 影响 | 缓解 |
|---|---|---|
| 密钥误提交/误打印 | 账户只读数据泄露 | gitignore + 掩码 + CI 扫描（阶段 3） |
| DSN 泄露到进程列表/历史 | DB 被访问 | 批次 3 改环境变量/文件（TD-SEC-001） |
| 本机其他进程读取 `work/` | 逆向证据与私有数据泄露 | 目录权限 700；D3 明确本地保留；不放到共享盘 |
| 代理/MITM | 请求被截获 | 只用 TLS；不关闭证书校验；不使用不明代理脚本 |
| 依赖投毒 | 代码执行 | 核心零依赖；可选依赖锁版本（TD-DEP-001） |

## 5. 事件响应

1. **怀疑密钥泄露**：立即在币安后台删除该 Key → 新建只读 Key → 检查是否有异常请求记录 → 复盘泄露路径。
2. **私有数据误提交**：从 git 历史移除（`git filter-repo` 或重建分支）→ 删除远端 → 轮换相关密钥 →
   在 `tech-debt-tracker.md` 记录并写明教训。
3. **误把 `work/` 加入提交**：`git reset` 取消暂存；确认 `.gitignore` 生效；不要用 `git add -f`。

## 6. 待补的安全能力（批次 3）

- [ ] CI 密钥扫描（当前为本地脚本；加 `.secretsignore` 区分文档占位符）
- [ ] DSN/密钥只经环境变量或受限文件传递（`BINANCE_PG_DSN`、`--pg-dsn-file`）
- [ ] 提交前 hook：禁止 `work/`、`.env`、`*key*.txt` 进入索引
- [ ] 依赖锁定与漏洞扫描（`pip-audit` 或等价）
