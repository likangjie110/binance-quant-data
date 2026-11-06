#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ruff_gate.py —— 带迁移基线的 ruff 门禁

为什么不用裸 `ruff check`：阶段 3 不允许改业务代码，而存量有 5 条违规（见基线文件）。
本门禁只保证"不新增违规"，并提示基线何时可收紧；批次 1/2 清理后基线归零。

用法：
  python3 scripts/gates/ruff_gate.py                      # 自动找 ruff
  python3 scripts/gates/ruff_gate.py --ruff .venv/bin/ruff
  python3 scripts/gates/ruff_gate.py --targets tools scripts tests
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASELINE = os.path.join(ROOT, "scripts", "gates", "ruff_baseline.txt")


def find_ruff(explicit: str | None) -> str:
    if explicit:
        return explicit
    venv_ruff = os.path.join(ROOT, ".venv", "bin", "ruff")
    if os.path.exists(venv_ruff):
        return venv_ruff
    found = shutil.which("ruff")
    if found:
        return found
    raise SystemExit("找不到 ruff：pip install -r requirements-dev.txt")


def load_baseline() -> dict[tuple[str, str], int]:
    allowed: dict[tuple[str, str], int] = {}
    if not os.path.exists(BASELINE):
        return allowed
    for line in open(BASELINE, "r", encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3:
            raise SystemExit(f"基线格式错误：{line!r}（应为 path rule count）")
        path, rule, count = parts
        allowed[(path.replace("\\", "/"), rule)] = int(count)
    return allowed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ruff", default=None)
    ap.add_argument("--targets", nargs="+", default=["tools", "scripts", "tests"])
    args = ap.parse_args()

    ruff = find_ruff(args.ruff)
    proc = subprocess.run(
        [ruff, "check", "--output-format", "json", *args.targets],
        cwd=ROOT, capture_output=True, text=True,
    )
    try:
        findings = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        print(f"无法解析 ruff 输出：\n{proc.stdout}\n{proc.stderr}", file=sys.stderr)
        return 2

    counts: collections.Counter = collections.Counter()
    samples: dict[tuple[str, str], str] = {}
    for f in findings:
        rel = os.path.relpath(f.get("filename", ""), ROOT).replace("\\", "/")
        code = f.get("code") or "?"
        key = (rel, code)
        counts[key] += 1
        samples.setdefault(key, f.get("message", ""))

    baseline = load_baseline()
    new_violations, stale = [], []
    for key, n in sorted(counts.items()):
        allowed = baseline.get(key, 0)
        if n > allowed:
            new_violations.append((key, n, allowed, samples[key]))
    for key, allowed in sorted(baseline.items()):
        actual = counts.get(key, 0)
        if actual < allowed:
            stale.append((key, allowed, actual))

    if stale:
        print("基线可收紧（存量已减少，请更新 scripts/gates/ruff_baseline.txt）：")
        for (path, rule), allowed, actual in stale:
            print(f"  - {path} {rule}: 基线 {allowed} → 实际 {actual}")

    if new_violations:
        print(f"ruff 新增违规 {len(new_violations)} 组：")
        for (path, rule), n, allowed, msg in new_violations:
            print(f"  - {path} {rule}: {n}（基线 {allowed}）{msg}")
        return 1

    total = sum(counts.values())
    allowed_total = sum(baseline.values())
    print(f"ruff 通过：{total} 条存量违规（基线 {allowed_total} 条，未新增）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
