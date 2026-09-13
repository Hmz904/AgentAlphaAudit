#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$ROOT/outputs"
rm -f "$ROOT/outputs/demo.sqlite"
python -m agent_alpha_audit ingest-rdagent \
  --events "$ROOT/examples/rdagent_events.jsonl" \
  --db "$ROOT/outputs/demo.sqlite" --run-id demo
python -m agent_alpha_audit export-eval-manifest \
  --db "$ROOT/outputs/demo.sqlite" --run-id demo \
  --out "$ROOT/outputs/strict_eval_manifest_demo.json"
python -m agent_alpha_audit report \
  --db "$ROOT/outputs/demo.sqlite" --run-id demo \
  --returns-csv "$ROOT/examples/trial_returns.csv" \
  --out "$ROOT/outputs/demo_report.json"
python -m agent_alpha_audit scorecard \
  --evidence "$ROOT/examples/audit_evidence.json" \
  --out "$ROOT/outputs/AGENT_ALPHA_SCORECARD_DEMO.md" \
  --title "Agent Alpha Scorecard — intentionally incomplete synthetic demo"
python -m agent_alpha_audit waterfall \
  --stages "$ROOT/examples/stage_metrics.json" \
  --out "$ROOT/outputs/audit_waterfall_demo.svg" --metric Sharpe
