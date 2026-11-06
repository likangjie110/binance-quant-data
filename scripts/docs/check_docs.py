#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_docs.py —— 文档防腐门禁（阶段 2）

检查项：
  1. 必需文件存在（AGENTS/ARCHITECTURE/QUALITY_SCORE/索引/计划/生成物…）
  2. AGENTS.md 行数 ≤ 200，且含必需小节
  3. 所有 Markdown 相对链接可解析（跳过代码块/外链/纯锚点/图片）
  4. docs/index.md 索引了全部文档（docs 下所有 .md + 根文档）
  5. docs/generated/db-schema.md 与 sql/ 事实源一致（调用生成器 --check）
  6. 无未登记占位符（"待补充"）
  7. 输出校验统计；任何失败退出码 1

用法：
  python3 scripts/docs/check_docs.py
  python3 scripts/docs/check_docs.py --quiet
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKIP_DIRS = {".git", ".venv", "work", "__pycache__", "node_modules", ".idea", "scan", ".pytest_cache", ".ruff_cache"}
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE_RE = re.compile(r"```.*?```", re.S)
PLACEHOLDER_RE = re.compile(r"待补充|待填写|TBD")

REQUIRED_FILES = [
    "AGENTS.md",
    "ARCHITECTURE.md",
    "docs/index.md",
    "docs/QUALITY_SCORE.md",
    "docs/CI.md",
    "docs/DEVELOPMENT.md",
    "docs/RELIABILITY.md",
    "docs/SECURITY.md",
    "docs/TROUBLESHOOTING.md",
    "docs/design-docs/index.md",
    "docs/design-docs/core-beliefs.md",
    "docs/design-docs/decisions.md",
    "docs/product-specs/index.md",
    "docs/references/index.md",
    "docs/generated/db-schema.md",
    "docs/exec-plans/tech-debt-tracker.md",
    "docs/exec-plans/completed/README.md",
    "docs/exec-plans/active/harness-migration.md",
]

AGENTS_REQUIRED_SECTIONS = [
    "## 这是什么项目",
    "## 如何开始",
    "## 硬性约束",
    "## 常用命令",
    "## 目录地图",
    "## 下一步去哪儿看",
]

ROOT_INDEX_TARGETS = [
    "README.md", "AGENTS.md", "ARCHITECTURE.md",
    "币安数据源分析报告.md", "用户数据流接入指南.md",
]


def iter_md(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".md"):
                yield os.path.join(dirpath, fn)


def rel_links(text: str):
    text = FENCE_RE.sub("", text)
    out = []
    for m in LINK_RE.finditer(text):
        target = m.group(1).strip()
        if target.startswith(("http://", "https://", "mailto:", "#", "tel:")):
            continue
        target = target.split("#", 1)[0]
        if target:
            out.append(target)
    return out


def check_links(md_files):
    failures = []
    checked = 0
    for path in md_files:
        base = os.path.dirname(path)
        try:
            text = open(path, "r", encoding="utf-8").read()
        except OSError as e:
            failures.append(f"{path}: 无法读取（{e}）")
            continue
        for target in rel_links(text):
            resolved = os.path.normpath(os.path.join(base, target))
            checked += 1
            if not os.path.exists(resolved):
                failures.append(f"{os.path.relpath(path, ROOT)}: 链接失效 → {target}")
    return checked, failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    failures: list[str] = []
    warnings: list[str] = []

    # 1) 必需文件
    for f in REQUIRED_FILES:
        if not os.path.exists(os.path.join(ROOT, f)):
            failures.append(f"缺少必需文件：{f}")

    # 2) AGENTS.md
    agents = os.path.join(ROOT, "AGENTS.md")
    if os.path.exists(agents):
        lines = open(agents, "r", encoding="utf-8").read().splitlines()
        if len(lines) > 200:
            failures.append(f"AGENTS.md 过长：{len(lines)} 行（上限 200）")
        text = "\n".join(lines)
        for sec in AGENTS_REQUIRED_SECTIONS:
            if sec not in text:
                failures.append(f"AGENTS.md 缺少必需小节：{sec}")
        if len(lines) > 120:
            warnings.append(f"AGENTS.md {len(lines)} 行，建议压到 ~100 行")

    # 3) 链接
    md_files = sorted(iter_md(ROOT))
    checked, link_failures = check_links(md_files)
    failures.extend(link_failures)

    # 4) docs/index.md 索引完整性
    index_path = os.path.join(ROOT, "docs/index.md")
    indexed_targets = []
    if os.path.exists(index_path):
        index_text = open(index_path, "r", encoding="utf-8").read()
        indexed_targets = index_text
    docs_dir = os.path.join(ROOT, "docs")
    missing_index = []
    for path in md_files:
        r = os.path.relpath(path, ROOT)
        if r == os.path.join("docs", "index.md"):
            continue
        # 以 docs/index.md 为基准的精确相对链接目标（允许带 query/anchor 已剥离）
        target = os.path.relpath(path, docs_dir)
        if f"]({target})" not in indexed_targets:
            missing_index.append(f"{r}（期望链接 ({target}) ）")
    for r in missing_index:
        failures.append(f"docs/index.md 未索引：{r}")

    # 5) 生成物新鲜度
    gen = os.path.join(ROOT, "scripts", "docs", "gen_db_schema.py")
    if os.path.exists(gen):
        proc = subprocess.run([sys.executable, gen, "--check"], capture_output=True, text=True, cwd=ROOT)
        if proc.returncode != 0:
            failures.append("db-schema.md 与 sql/ 不一致：" + (proc.stderr or proc.stdout).strip())

    # 6) 占位符（规则文档除外）
    placeholders = []
    for path in md_files:
        r = os.path.relpath(path, ROOT)
        if r.startswith(os.path.join("docs", "HARNESS-RULES")):
            continue
        text = open(path, "r", encoding="utf-8").read()
        if PLACEHOLDER_RE.search(text):
            placeholders.append(r)
    for r in placeholders:
        failures.append(f"存在未登记占位符（{PLACEHOLDER_RE.pattern}）：{r}")

    # 7) 报告
    if not args.quiet:
        print(f"文档文件：{len(md_files)} 个；检查链接 {checked} 条")
        if warnings:
            print(f"警告 {len(warnings)}：")
            for w in warnings:
                print(f"  - {w}")
        if failures:
            print(f"失败 {len(failures)}：")
            for f in failures:
                print(f"  - {f}")
        else:
            print("DOC CHECK PASS")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
