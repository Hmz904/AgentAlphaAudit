from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapters import RDAgentSidecarAdapter
from .audit.report import build_run_report, write_json
from .audit.scorecard import render_markdown
from .audit.waterfall import plot_audit_waterfall
from .ledger import TrialLedger
from .models import AuditEvidence
from .runlock import validate_run_lock
from .strict_eval import assemble_trial_returns, export_strict_eval_manifest, run_external_evaluator


def cmd_ingest(args: argparse.Namespace) -> None:
    adapter = RDAgentSidecarAdapter()
    trials = adapter.parse(args.events, args.run_id)
    ledger = TrialLedger(args.db)
    for t in trials:
        ledger.upsert(t)
    ledger.close()
    print(json.dumps({"run_id": args.run_id, "ingested_trials": len(trials), "db": str(args.db)}))


def cmd_report(args: argparse.Namespace) -> None:
    report = build_run_report(
        args.db,
        args.run_id,
        returns_csv=args.returns_csv,
        winner_column=args.winner_column,
        winner_override_reason=args.winner_override_reason,
        periods_per_year=args.periods_per_year,
        min_effective_trial_coverage=args.min_effective_trial_coverage,
    )
    if args.out:
        write_json(report, args.out)
    print(json.dumps(report, indent=2, sort_keys=True))


def cmd_scorecard(args: argparse.Namespace) -> None:
    data = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    evidence = AuditEvidence(**data)
    md = render_markdown(evidence, args.title)
    Path(args.out).write_text(md, encoding="utf-8")
    print(json.dumps({"scorecard": str(args.out)}))


def cmd_waterfall(args: argparse.Namespace) -> None:
    data = json.loads(Path(args.stages).read_text(encoding="utf-8"))
    stages = data.get(args.metric.lower(), data)
    plot_audit_waterfall(stages, args.out, metric=args.metric)
    print(json.dumps({"waterfall": str(args.out)}))




def cmd_export_eval_manifest(args: argparse.Namespace) -> None:
    m = export_strict_eval_manifest(args.db, args.run_id, args.out)
    print(json.dumps({"manifest": str(args.out), "raw_trials_lower_bound": m["raw_trials_lower_bound"]}))


def cmd_run_strict_evaluator(args: argparse.Namespace) -> None:
    result = run_external_evaluator(args.manifest, args.out_dir, args.command, timeout_seconds=args.timeout_seconds)
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_assemble_returns(args: argparse.Namespace) -> None:
    result = assemble_trial_returns(args.manifest, args.eval_dir, args.out, args.coverage_json)
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_validate_lock(args: argparse.Namespace) -> None:
    data = validate_run_lock(args.lock, require_locked=not args.allow_draft)
    print(json.dumps({"valid": True, "status": data.get("status"), "lock": str(args.lock)}))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent-alpha-audit")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest-rdagent", help="Ingest RD-Agent probe JSONL into the immutable trial ledger")
    s.add_argument("--events", required=True)
    s.add_argument("--db", required=True)
    s.add_argument("--run-id", required=True)
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("report", help="Produce trial accounting and optional DSR/effective-trial diagnostics")
    s.add_argument("--db", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--returns-csv")
    s.add_argument("--winner-column", help="Manual override only; default winner is inferred from the agent ledger")
    s.add_argument("--winner-override-reason", help="Required whenever --winner-column is supplied")
    s.add_argument("--periods-per-year", type=int, default=252)
    s.add_argument("--min-effective-trial-coverage", type=float, default=0.80)
    s.add_argument("--out")
    s.set_defaults(func=cmd_report)


    s = sub.add_parser("export-eval-manifest", help="Export ALL captured trials for deterministic strict reevaluation")
    s.add_argument("--db", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_export_eval_manifest)

    s = sub.add_parser("run-strict-evaluator", help="Invoke an external deterministic evaluator for every trial and cumulative library state")
    s.add_argument("--manifest", required=True)
    s.add_argument("--out-dir", required=True)
    s.add_argument("--command", required=True, help="Command template containing {request} and {outdir}; executed with shell=False")
    s.add_argument("--timeout-seconds", type=int, default=1800)
    s.set_defaults(func=cmd_run_strict_evaluator)

    s = sub.add_parser("assemble-returns", help="Assemble per-trial validation_returns.csv files into aligned trial_returns.csv")
    s.add_argument("--manifest", required=True)
    s.add_argument("--eval-dir", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--coverage-json")
    s.set_defaults(func=cmd_assemble_returns)

    s = sub.add_parser("scorecard", help="Render the proposed Agent Alpha Scorecard")
    s.add_argument("--evidence", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--title", default="Agent Alpha Scorecard")
    s.set_defaults(func=cmd_scorecard)

    s = sub.add_parser("validate-lock", help="Validate a frozen confirmatory run lock")
    s.add_argument("--lock", required=True)
    s.add_argument("--allow-draft", action="store_true")
    s.set_defaults(func=cmd_validate_lock)

    s = sub.add_parser("waterfall", help="Render reported-to-audited metric decay")
    s.add_argument("--stages", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--metric", default="Sharpe")
    s.set_defaults(func=cmd_waterfall)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
