#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_project.py —— harness 阶段 1 只读扫描器

产出（供 docs/exec-plans/active/ 引用）：
  * 仓库地图：目录/文件/入口点/LOC
  * 复杂度热点：函数长度、控制流分支数、嵌套深度
  * 重复代码：跨文件 8 行窗口指纹
  * 本地模块依赖图
  * 高风险字面量扫描（密钥/凭证/连接串）
  * TODO/FIXME 清单

只读：不修改任何被扫描文件；输出写到 --out（默认 docs/exec-plans/active/scan）。
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

SKIP_DIRS = {".git", ".venv", "work", "__pycache__", "node_modules", ".idea", "scan"}
SCAN_EXTS = {".py", ".sql", ".md", ".sh", ".toml", ".yaml", ".yml", ".json", ".txt"}

BRANCH_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try,
                ast.With, ast.AsyncWith, ast.BoolOp)
NEST_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith)


def iter_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            ext = os.path.splitext(fn)[1]
            if ext not in SCAN_EXTS:
                continue
            path = os.path.join(dirpath, fn)
            yield path


def rel(root: str, path: str) -> str:
    return os.path.relpath(path, root)


def count_lines(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def module_name(root: str, path: str) -> str:
    r = rel(root, path)
    return r[:-3].replace(os.sep, ".") if r.endswith(".py") else r


def scan_python(root: str, path: str):
    """返回 (imports, functions, max_nesting, todo_lines)"""
    out = {"imports": [], "functions": [], "todos": [], "syntax_error": None, "top_nesting": 0}
    try:
        src = open(path, "r", encoding="utf-8", errors="replace").read()
        tree = ast.parse(src, filename=path)
    except SyntaxError as e:
        out["syntax_error"] = f"{e.msg} (line {e.lineno})"
        return out
    lines = src.splitlines()

    class ImportVisitor(ast.NodeVisitor):
        def visit_Import(self, node):
            for a in node.names:
                out["imports"].append(a.name.split(".")[0])

        def visit_ImportFrom(self, node):
            if node.module and node.level == 0:
                out["imports"].append(node.module.split(".")[0])

    ImportVisitor().visit(tree)

    def depth(node, d=0):
        best = d
        for child in ast.iter_child_nodes(node):
            nd = d + 1 if isinstance(child, NEST_NODES) else d
            best = max(best, depth(child, nd))
        return best

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            branches = sum(1 for n in ast.walk(node) if isinstance(n, BRANCH_NODES))
            nesting = depth(node)
            out["functions"].append({
                "name": node.name, "line": node.lineno, "length": length,
                "branches": branches, "approx_cc": 1 + branches, "nesting": nesting,
            })
            out["top_nesting"] = max(out["top_nesting"], nesting)

    if path.endswith("scan_project.py"):
        return out  # 避免扫描器自身的正则/文档自命中
    for i, line in enumerate(lines, 1):
        if re.search(r"\b(TODO|FIXME|XXX|HACK)\b", line) and ("#" in line or "//" in line):
            out["todos"].append({"line": i, "text": line.strip()[:160]})
    return out


def normalized_windows(path: str, size: int = 8):
    try:
        raw = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return []
    norm = []
    for line in raw:
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("//"):
            norm.append("")
        else:
            s = re.sub(r"\s+", " ", s)
            norm.append(s)
    wins = []
    for i in range(len(norm) - size + 1):
        block = "\n".join(norm[i:i + size])
        if block.count("\n") < size - 1:
            continue
        meaningful = sum(1 for x in norm[i:i + size] if x)
        if meaningful < size - 1:
            continue
        wins.append({"file": path, "line": i + 1,
                     "hash": hashlib.sha1(block.encode()).hexdigest()[:16]})
    return wins


SECRET_PATTERNS = [
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pg_url_with_password", re.compile(r"postgres(?:ql)?://[^\s:/]+:[^\s:@]+@")),
    ("hardcoded_secret_assign", re.compile(
        r"(?i)\b(api[_-]?key|api[_-]?secret|secret[_-]?key|password|passwd|token)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{20,}")),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="docs/exec-plans/active/scan")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    os.makedirs(args.out, exist_ok=True)

    files = sorted(iter_files(root))
    inventory = []
    py_imports = defaultdict(list)
    functions = []
    todos = []
    windows = []
    secret_hits = []

    for path in files:
        r = rel(root, path)
        ext = os.path.splitext(path)[1]
        loc = count_lines(path)
        inventory.append({"path": r, "ext": ext, "bytes": os.path.getsize(path), "loc": loc})
        if ext == ".py":
            info = scan_python(root, path)
            if info["syntax_error"]:
                inventory[-1]["syntax_error"] = info["syntax_error"]
            for imp in info["imports"]:
                py_imports[r].append(imp)
            for fn in info["functions"]:
                fn["file"] = r
                functions.append(fn)
            for t in info["todos"]:
                t["file"] = r
                todos.append(t)
            windows.extend(normalized_windows(path))
        if ext in (".py", ".sh", ".sql", ".md", ".json", ".toml", ".yaml", ".yml"):
            try:
                text = open(path, "r", encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for name, pat in SECRET_PATTERNS:
                for m in pat.finditer(text):
                    line = text.count("\n", 0, m.start()) + 1
                    snippet = text[m.start():m.end()]
                    if name == "pg_url_with_password":
                        snippet = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", snippet)
                    secret_hits.append({"file": r, "line": line, "kind": name,
                                        "snippet": snippet[:120]})

    # 重复窗口聚类
    by_hash = defaultdict(list)
    for w in windows:
        by_hash[w["hash"]].append(w)
    dup_clusters = []
    for h, ws in by_hash.items():
        files_in = {w["file"] for w in ws}
        if len(files_in) >= 2:
            dup_clusters.append({"hash": h, "files": sorted(files_in),
                                 "locations": [f"{w['file']}:{w['line']}" for w in ws[:6]]})
    dup_clusters.sort(key=lambda x: -len(x["files"]))

    # 本地模块依赖（只保留同仓库模块名）
    local_mods = {module_name(root, p) for p in files if p.endswith(".py")}
    dep_edges = []
    for f, imps in py_imports.items():
        for imp in set(imps):
            if imp in local_mods or any(m.split(".")[-1] == imp for m in local_mods):
                dep_edges.append({"from": f, "to": imp})
    ext_imports = Counter()
    for imps in py_imports.values():
        for imp in imps:
            if imp not in local_mods and not any(m.split(".")[-1] == imp for m in local_mods):
                ext_imports[imp] += 1

    py_files = [i for i in inventory if i["ext"] == ".py"]
    big_functions = sorted(functions, key=lambda f: -f["length"])[:15]
    hot_cc = sorted(functions, key=lambda f: -f["approx_cc"])[:15]

    result = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": root,
        "summary": {
            "files": len(inventory),
            "py_files": len(py_files),
            "py_loc": sum(i["loc"] for i in py_files),
            "all_loc": sum(i["loc"] for i in inventory),
            "functions": len(functions),
            "dup_clusters": len(dup_clusters),
            "secret_hits": len(secret_hits),
            "todos": len(todos),
        },
        "inventory": inventory,
        "dependency_edges": dep_edges,
        "external_imports": dict(ext_imports.most_common(30)),
        "big_functions": big_functions,
        "hot_cc": hot_cc,
        "duplication": dup_clusters[:20],
        "secrets": secret_hits,
        "todos": todos,
    }
    with open(os.path.join(args.out, "scan.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    # Markdown 摘要
    md = []
    md.append("# 项目扫描报告（阶段 1 · 只读）\n")
    md.append(f"- 生成时间：{result['generated_at']}")
    md.append(f"- 根目录：`{root}`")
    s = result["summary"]
    md.append(f"- 文件 {s['files']} 个（.py {s['py_files']} 个），Python 代码 {s['py_loc']} 行，全量 {s['all_loc']} 行")
    md.append(f"- 函数 {s['functions']} 个；跨文件重复窗口 {s['dup_clusters']} 组；疑似密钥/凭证 {s['secret_hits']} 处；TODO/FIXME {s['todos']} 处\n")

    md.append("## 文件清单（按 LOC 降序）\n")
    md.append("| 文件 | 行数 | 字节 |")
    md.append("|---|---:|---:|")
    for i in sorted(inventory, key=lambda x: -x["loc"])[:25]:
        md.append(f"| `{i['path']}` | {i['loc']} | {i['bytes']} |")

    md.append("\n## 复杂度热点：最长函数\n")
    md.append("| 文件:行 | 函数 | 长度 | 分支 | 近似圈复杂度 | 嵌套深度 |")
    md.append("|---|---|---:|---:|---:|---:|")
    for f in big_functions:
        md.append(f"| `{f['file']}:{f['line']}` | `{f['name']}` | {f['length']} | {f['branches']} | {f['approx_cc']} | {f['nesting']} |")

    md.append("\n## 复杂度热点：分支最多\n")
    md.append("| 文件:行 | 函数 | 长度 | 分支 | 近似圈复杂度 |")
    md.append("|---|---|---:|---:|---:|")
    for f in hot_cc:
        md.append(f"| `{f['file']}:{f['line']}` | `{f['name']}` | {f['length']} | {f['branches']} | {f['approx_cc']} |")

    md.append("\n## 跨文件重复代码（8 行窗口）\n")
    if not dup_clusters:
        md.append("无跨文件重复窗口。")
    for c in dup_clusters[:10]:
        md.append(f"- `{c['hash']}` → {', '.join('`'+f+'`' for f in c['files'])}")
        md.append(f"  - 位置：{', '.join(c['locations'])}")

    md.append("\n## 本地模块依赖\n")
    if not dep_edges:
        md.append("（无本地模块导入）")
    for e in dep_edges:
        md.append(f"- `{e['from']}` → `{e['to']}`")

    md.append("\n## 第三方依赖（import 统计）\n")
    for k, v in result["external_imports"].items():
        md.append(f"- `{k}` × {v}")

    md.append("\n## 疑似密钥/凭证（已脱敏）\n")
    if not secret_hits:
        md.append("未命中。")
    for h in secret_hits[:30]:
        md.append(f"- `{h['file']}:{h['line']}` [{h['kind']}] `{h['snippet']}`")

    md.append("\n## TODO / FIXME\n")
    if not todos:
        md.append("未发现。")
    for t in todos[:30]:
        md.append(f"- `{t['file']}:{t['line']}` {t['text']}")

    with open(os.path.join(args.out, "scan-report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    print(json.dumps(s, ensure_ascii=False))
    print(f"written: {args.out}/scan.json, {args.out}/scan-report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
