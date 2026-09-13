from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd

from .ledger import TrialLedger
from .utils import sha256_file


def _trial_sort_key(t):
    s = str(t.trial_id)
    return (not s.isdigit(), int(s) if s.isdigit() else s)


def export_strict_eval_manifest(ledger_path: str | Path, run_id: str, out_path: str | Path) -> dict[str, Any]:
    """Export both search units and the cumulative factor-library outcome path.

    Search unit: every captured emitted trial (for search accounting / DSR / redundancy).
    Primary outcome unit: cumulative factor library at loop k (for the RD-Agent factor
    mining outcome/waterfall). This avoids pretending that one 'winner factor' is the
    object RD-Agent actually reports.
    """
    ledger = TrialLedger(ledger_path)
    trials = sorted(ledger.trials(run_id), key=_trial_sort_key)
    ledger.close()

    trial_items = []
    cumulative_items = []
    cumulative_exprs: list[str] = []
    seen: set[str] = set()
    for t in trials:
        exprs = list(t.factor_expressions or [])
        trial_items.append({
            "run_id": run_id,
            "trial_id": t.trial_id,
            "evaluation_unit": "trial_experiment",
            "action": t.action,
            "hypothesis": t.hypothesis,
            "factor_expressions": exprs,
            "strict_evaluator_required": True,
            "evaluable": bool(exprs),
            "reason_if_not_evaluable": None if exprs else "no factor expression captured",
        })
        # Prefer the runtime runner snapshot of successfully implemented cumulative
        # factors. Fall back to a deterministic union only for synthetic/legacy ledgers.
        runtime_cumulative = []
        raw_cum = (t.artifacts or {}).get("cumulative_factor_expressions")
        if raw_cum:
            try:
                parsed = json.loads(raw_cum)
                if isinstance(parsed, list):
                    runtime_cumulative = [str(x) for x in parsed if x]
            except json.JSONDecodeError:
                runtime_cumulative = []
        if runtime_cumulative:
            cumulative_exprs = []
            seen = set()
            for e in runtime_cumulative:
                if e not in seen:
                    seen.add(e)
                    cumulative_exprs.append(e)
            cumulative_source = "runner_successful_factor_state"
        else:
            for e in exprs:
                if e not in seen:
                    seen.add(e)
                    cumulative_exprs.append(e)
            cumulative_source = "fallback_union_of_captured_trial_expressions"
        cumulative_items.append({
            "run_id": run_id,
            "loop_k": t.trial_id,
            "evaluation_unit": "cumulative_factor_library_at_loop_k",
            "factor_expressions": list(cumulative_exprs),
            "cumulative_state_source": cumulative_source,
            "strict_evaluator_required": True,
            "evaluable": bool(cumulative_exprs),
            "reason_if_not_evaluable": None if cumulative_exprs else "no cumulative factor expressions captured yet",
        })

    primary = cumulative_items[-1] if cumulative_items else None
    manifest = {
        "schema": "agent-alpha-audit.strict-eval-manifest.v2",
        "run_id": run_id,
        "search_unit": "trial_experiment",
        "primary_outcome_unit": "cumulative_factor_library_at_loop_k",
        "policy": "ALL captured trials are evaluation targets; cumulative factor-library states are evaluated separately for the primary outcome",
        "raw_trials_lower_bound": len(trials),
        "trial_items": trial_items,
        "cumulative_library_items": cumulative_items,
        "primary_final_library": primary,
        # Backward-compatible alias for callers that only know trial items.
        "items": trial_items,
    }
    Path(out_path).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _output_dir_for_item(root: Path, item: dict[str, Any]) -> Path:
    if item.get("evaluation_unit") == "cumulative_factor_library_at_loop_k":
        return root / f"library_{item['loop_k']}"
    return root / f"trial_{item['trial_id']}"


def run_external_evaluator(
    manifest_path: str | Path,
    out_dir: str | Path,
    command_template: str,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    """Run a deterministic evaluator for every trial and cumulative library state.

    The command is formatted then tokenized with shlex and executed with shell=False.
    Each invocation receives a JSON request and must write result.json plus (for trial
    items) validation_returns.csv with columns date,return.
    """
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    all_items = list(manifest.get("trial_items", manifest.get("items", []))) + list(manifest.get("cumulative_library_items", []))
    results = []
    for item in all_items:
        unit_dir = _output_dir_for_item(root, item)
        unit_dir.mkdir(parents=True, exist_ok=True)
        request = unit_dir / "request.json"
        request.write_text(json.dumps(item, indent=2, sort_keys=True), encoding="utf-8")
        ident = item.get("trial_id", item.get("loop_k"))
        unit = item.get("evaluation_unit")
        if not item.get("evaluable"):
            results.append({"id": str(ident), "evaluation_unit": unit, "status": "not_evaluable"})
            continue
        formatted = command_template.format(request=str(request), outdir=str(unit_dir))
        argv = shlex.split(formatted)
        if not argv:
            raise ValueError("external evaluator command is empty")
        try:
            proc = subprocess.run(argv, shell=False, text=True, capture_output=True, timeout=int(timeout_seconds), check=False)
            status = "ok" if proc.returncode == 0 else "failed"
            returncode = proc.returncode
            stdout, stderr = proc.stdout or "", proc.stderr or ""
        except subprocess.TimeoutExpired as exc:
            status, returncode = "timeout", None
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        (unit_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
        (unit_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
        results.append({"id": str(ident), "evaluation_unit": unit, "status": status, "returncode": returncode})
    summary = {"manifest": str(manifest_path), "out_dir": str(root), "timeout_seconds": int(timeout_seconds), "results": results}
    (root / "RUN_SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def assemble_trial_returns(
    manifest_path: str | Path,
    eval_dir: str | Path,
    out_csv: str | Path,
    coverage_json: str | Path | None = None,
    require_identical_dates: bool = True,
) -> dict[str, Any]:
    """Assemble trial-level validation returns, rejecting unequal sample windows.

    Different date supports make cross-trial Sharpe dispersion incomparable because
    short series have noisier Sharpe estimates. The confirmatory default is therefore
    strict identical date coverage rather than an outer join.
    """
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    root = Path(eval_dir)
    series: list[pd.Series] = []
    details = []
    reference_index: pd.DatetimeIndex | None = None
    for item in manifest.get("trial_items", manifest.get("items", [])):
        tid = str(item["trial_id"])
        p = root / f"trial_{tid}" / "validation_returns.csv"
        if not p.exists():
            details.append({"trial_id": tid, "status": "missing_returns"})
            continue
        df = pd.read_csv(p)
        if not {"date", "return"}.issubset(df.columns):
            details.append({"trial_id": tid, "status": "invalid_schema"})
            continue
        s = pd.Series(pd.to_numeric(df["return"], errors="coerce").values, index=pd.to_datetime(df["date"]), name=f"trial_{tid}")
        s = s[~s.index.duplicated(keep="last")].sort_index().dropna()
        if reference_index is None:
            reference_index = pd.DatetimeIndex(s.index)
        elif require_identical_dates and not pd.DatetimeIndex(s.index).equals(reference_index):
            raise ValueError(
                f"trial {tid} validation dates differ from the reference trial; confirmatory Sharpe dispersion requires identical coverage"
            )
        series.append(s)
        details.append({
            "trial_id": tid,
            "status": "included",
            "sha256": sha256_file(p),
            "n": int(s.size),
            "start": s.index.min().date().isoformat() if len(s) else None,
            "end": s.index.max().date().isoformat() if len(s) else None,
        })
    aligned = pd.concat(series, axis=1, join="inner" if require_identical_dates else "outer").sort_index() if series else pd.DataFrame()
    aligned.index.name = "date"
    aligned.to_csv(out_csv)
    raw_n = int(manifest.get("raw_trials_lower_bound", len(manifest.get("trial_items", manifest.get("items", [])))))
    included = len(series)
    summary = {
        "schema": "agent-alpha-audit.return-coverage.v2",
        "raw_trials_lower_bound": raw_n,
        "trials_with_aligned_returns": included,
        "coverage": included / raw_n if raw_n else 0.0,
        "date_alignment_policy": "strict_identical" if require_identical_dates else "outer_union",
        "aligned_n": len(aligned),
        "aligned_start": aligned.index.min().date().isoformat() if len(aligned) else None,
        "aligned_end": aligned.index.max().date().isoformat() if len(aligned) else None,
        "output": str(out_csv),
        "details": details,
    }
    if coverage_json:
        Path(coverage_json).write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary
