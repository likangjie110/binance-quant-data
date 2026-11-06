#!/usr/bin/env bash
# 一键质量门禁：本地与 CI 跑同一份脚本
#
# 用法：
#   bash scripts/gates/check.sh
#   PYTHON=.venv/bin/python RUFF=.venv/bin/ruff bash scripts/gates/check.sh
#
# 覆盖：语法 → lint（带迁移基线）→ 单测 → 文档结构/链接 → 生成物一致性 → 密钥扫描
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT"

if [ -z "${PYTHON:-}" ] && [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
fi
PY="${PYTHON:-python3}"

if [ -z "${RUFF:-}" ]; then
  if [ -x "$ROOT/.venv/bin/ruff" ]; then
    RUFF="$ROOT/.venv/bin/ruff"
  elif command -v ruff >/dev/null 2>&1; then
    RUFF=$(command -v ruff)
  else
    echo "缺少 ruff：pip install -r requirements-dev.txt" >&2
    exit 1
  fi
fi

step() { printf '\n[%s] %s\n' "$1" "$2"; }

step "1/6" "语法编译（compileall）"
"$PY" -m compileall -q tools scripts tests

step "2/6" "ruff（迁移基线：不允许新增违规）"
"$PY" scripts/gates/ruff_gate.py --ruff "$RUFF"

step "3/6" "pytest"
"$PY" -m pytest -q

step "4/6" "文档结构 / 链接 / 占位符"
"$PY" scripts/docs/check_docs.py --quiet

step "5/6" "生成物一致性（db-schema）"
"$PY" scripts/docs/gen_db_schema.py --check

step "6/6" "密钥扫描（未忽略命中即失败）"
"$PY" scripts/analysis/scan_project.py --check-secrets

printf '\nGATE PASS\n'
