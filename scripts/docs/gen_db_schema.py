#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_db_schema.py —— 从 sql/binance_stream_schema.sql 生成 docs/generated/db-schema.md

为什么要有它：DDL 是唯一事实源，文档由脚本生成且禁止手改，避免"代码改了文档没改"。
输出必须是确定性的（无时间戳），这样 CI 可以对比生成结果与提交版本是否一致。

用法：
  python3 scripts/docs/gen_db_schema.py            # 写入 docs/generated/db-schema.md
  python3 scripts/docs/gen_db_schema.py --check    # 只校验，不一致则退出 1
"""
from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SQL_PATH = os.path.join(ROOT, "sql", "binance_stream_schema.sql")
OUT_PATH = os.path.join(ROOT, "docs", "generated", "db-schema.md")

TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.*?)\);", re.S | re.I)
INDEX_RE = re.compile(r"CREATE INDEX IF NOT EXISTS\s+(\w+)\s+ON\s+(\w+)\s*\(([^;]+)\);", re.S | re.I)


def parse_sql(text: str):
    tables = []
    for name, body in TABLE_RE.findall(text):
        cols, pk = [], []
        for raw in body.splitlines():
            line = raw.strip().rstrip(",")
            if not line:
                continue
            if line.upper().startswith("PRIMARY KEY"):
                m = re.search(r"\(([^)]+)\)", line)
                if m:
                    pk = [c.strip() for c in m.group(1).split(",")]
                continue
            if line.upper().startswith(("CONSTRAINT", "UNIQUE", "FOREIGN KEY")):
                continue
            m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s+([A-Za-z][A-Za-z0-9_()\s]*)", line)
            if not m:
                continue
            cname, ctype = m.group(1), " ".join(m.group(2).split()).upper()
            if "PRIMARY KEY" in ctype:
                ctype = ctype.replace("PRIMARY KEY", "").strip()
                pk.append(cname)
            cols.append((cname, ctype))
        tables.append({"name": name, "columns": cols, "pk": pk})
    indexes = [{"name": n, "table": t, "cols": [c.strip() for c in cols.split(",")]}
               for n, t, cols in INDEX_RE.findall(text)]
    return tables, indexes


def render(tables, indexes) -> str:
    lines = [
        "# 数据库表结构（自动生成）",
        "",
        "> ⚠️ **本文件由脚本生成，禁止手改**。",
        "> 事实源：`sql/binance_stream_schema.sql`；生成命令：`python3 scripts/docs/gen_db_schema.py`。",
        "> CI 会校验本文件与事实源一致（`gen_db_schema.py --check`）。",
        "",
        f"共 {len(tables)} 张表。",
        "",
    ]
    for t in tables:
        lines.append(f"## `{t['name']}`")
        lines.append("")
        lines.append("| 列 | 类型 | 主键 |")
        lines.append("|---|---|---|")
        for col, ctype in t["columns"]:
            lines.append(f"| `{col}` | `{ctype}` | {'✓' if col in t['pk'] else ''} |")
        lines.append("")
        if t["pk"]:
            lines.append(f"主键：`({', '.join(t['pk'])})`")
            lines.append("")
    if indexes:
        lines.append("## 索引")
        lines.append("")
        lines.append("| 索引 | 表 | 列 |")
        lines.append("|---|---|---|")
        for i in indexes:
            lines.append(f"| `{i['name']}` | `{i['table']}` | `{', '.join(i['cols'])}` |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验生成结果是否与已提交文件一致")
    args = ap.parse_args()

    with open(SQL_PATH, "r", encoding="utf-8") as f:
        tables, indexes = parse_sql(f.read())
    content = render(tables, indexes)

    if args.check:
        if not os.path.exists(OUT_PATH):
            print(f"缺少生成文件: {OUT_PATH}（运行 gen_db_schema.py）", file=sys.stderr)
            return 1
        current = open(OUT_PATH, "r", encoding="utf-8").read()
        if current != content:
            print("db-schema.md 与 sql/ 不一致：请重跑 scripts/docs/gen_db_schema.py", file=sys.stderr)
            return 1
        print(f"db-schema.md 一致（{len(tables)} 张表）")
        return 0

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"written: {OUT_PATH}（{len(tables)} 张表，{len(indexes)} 个索引）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
