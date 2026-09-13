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


def export_strict_eval_manifest(
    ledger_path: str | Path,
    run_id: str,
    out_path: str | Path,
) -> dict[str, Any]:
    """Export captured search units and cumulative-library outcome states.

    Important distinction:

    * captured / has_factor_representation:
      evidence exists in the sidecar/ledger.
    * strict_replay_ready:
      enough executable implementation + evaluation-contract evidence exists
      to claim deterministic strict reevaluation.

    A factor expression or proposal alone is NOT treated as deterministic
    replay readiness.
    """
    ledger = TrialLedger(ledger_path)
    trials = sorted(ledger.trials(run_id), key=_trial_sort_key)
    ledger.close()

    def artifact_present(t, key: str) -> bool:
        value = (t.artifacts or {}).get(key)
        if value is None:
            return False
        if isinstance(value, str):
            value = value.strip()
            return value not in {"", "null", "None", "[]", "{}"}
        return bool(value)

    def observed_tags(t) -> set[str]:
        raw = (t.artifacts or {}).get("id_sources")
        if not raw:
            return set()
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, json.JSONDecodeError):
            return set()
        return set(parsed) if isinstance(parsed, dict) else set()

    def runtime_cumulative_state(t) -> list[str]:
        raw = (t.artifacts or {}).get("cumulative_factor_expressions")
        if not raw:
            return []
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(parsed, list):
            return []

        out: list[str] = []
        seen: set[str] = set()
        for value in parsed:
            if not value:
                continue
            value = str(value)
            if value not in seen:
                seen.add(value)
                out.append(value)
        return out

    trial_items: list[dict[str, Any]] = []
    cumulative_items: list[dict[str, Any]] = []

    # This state changes ONLY when a real runner snapshot is observed.
    # Failed/no-runner loops carry the previous successful state forward.
    cumulative_exprs: list[str] = []

    for t in trials:
        exprs = list(t.factor_expressions or [])
        tags = observed_tags(t)

        implementation_artifact_present = artifact_present(
            t, "implementation_artifact"
        )
        evaluation_spec_present = artifact_present(
            t, "evaluation_spec"
        )

        strict_replay_ready = bool(
            exprs
            and implementation_artifact_present
            and evaluation_spec_present
        )

        if not exprs:
            replay_reason = "no factor representation captured"
        elif not implementation_artifact_present:
            replay_reason = "implementation artifact not captured"
        elif not evaluation_spec_present:
            replay_reason = "evaluation spec not bound"
        else:
            replay_reason = None

        trial_items.append(
            {
                "run_id": run_id,
                "trial_id": t.trial_id,
                "evaluation_unit": "trial_experiment",
                "action": t.action,
                "hypothesis": t.hypothesis,
                "factor_expressions": exprs,
                "code_hash": t.code_hash,
                "captured": True,
                "has_factor_representation": bool(exprs),
                "coder_result_observed": "coder_result" in tags,
                "runner_result_observed": "runner_result" in tags,
                "implementation_artifact_present": (
                    implementation_artifact_present
                ),
                "evaluation_spec_present": evaluation_spec_present,
                "strict_replay_ready": strict_replay_ready,
                # Backward-compatible execution gate.
                "evaluable": strict_replay_ready,
                "strict_evaluator_required": True,
                "reason_if_not_evaluable": replay_reason,
            }
        )

        runtime_state = runtime_cumulative_state(t)

        if runtime_state:
            cumulative_exprs = runtime_state
            cumulative_source = "runner_successful_factor_state"
            runner_snapshot_observed = True
        elif cumulative_exprs:
            # Do NOT union proposal expressions from a failed/no-runner loop.
            cumulative_source = "carried_forward_last_runner_state"
            runner_snapshot_observed = False
        else:
            cumulative_source = "no_successful_runner_state_observed"
            runner_snapshot_observed = False

        # v3 deliberately refuses to call a library deterministically replayable
        # until executable implementations and a complete evaluation spec are
        # explicitly bound by the strict-evaluator contract.
        library_replay_ready = False

        cumulative_items.append(
            {
                "run_id": run_id,
                "loop_k": t.trial_id,
                "constructed_at_loop_k": t.trial_id,
                "evaluation_unit": "cumulative_factor_library_at_loop_k",
                "factor_expressions": list(cumulative_exprs),
                "factor_count": len(cumulative_exprs),
                "cumulative_state_source": cumulative_source,
                "runner_snapshot_observed": runner_snapshot_observed,
                "state_observed": bool(cumulative_exprs),
                "strict_replay_ready": library_replay_ready,
                # Backward-compatible execution gate.
                "evaluable": library_replay_ready,
                "strict_evaluator_required": True,
                "reason_if_not_evaluable": (
                    "implementation artifacts and complete evaluation spec "
                    "not yet bound for cumulative-library replay"
                    if cumulative_exprs
                    else "no successful cumulative runner state observed yet"
                ),
            }
        )

    successful_runner_states = [
        item
        for item in cumulative_items
        if item["cumulative_state_source"]
        == "runner_successful_factor_state"
    ]

    primary = (
        successful_runner_states[-1]
        if successful_runner_states
        else None
    )

    manifest = {
        "schema": "agent-alpha-audit.strict-eval-manifest.v3",
        "run_id": run_id,
        "search_unit": "trial_experiment",
        "primary_outcome_unit": "cumulative_factor_library_at_loop_k",
        "policy": (
            "ALL captured trials remain search-accounting targets; "
            "strict replay readiness requires executable implementation "
            "artifacts plus an explicit evaluation specification. "
            "Cumulative state changes only on observed runner snapshots."
        ),
        "raw_trials_lower_bound": len(trials),
        "captured_trial_count": len(trials),
        "trial_factor_representation_count": sum(
            bool(x["has_factor_representation"])
            for x in trial_items
        ),
        "strict_replay_ready_trial_count": sum(
            bool(x["strict_replay_ready"])
            for x in trial_items
        ),
        "observed_runner_snapshot_count": len(successful_runner_states),
        "strict_replay_ready_cumulative_count": sum(
            bool(x["strict_replay_ready"])
            for x in cumulative_items
        ),
        "trial_items": trial_items,
        "cumulative_library_items": cumulative_items,
        "primary_final_library": primary,
        "primary_final_library_loop_k": (
            primary["loop_k"] if primary else None
        ),
        # Backward-compatible alias for callers that only know trial items.
        "items": trial_items,
    }

    Path(out_path).write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
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
    reference_calendar_csv: str | Path | None = None,
    evaluation_spec_path: str | Path | None = None,
) -> dict[str, Any]:
    """Assemble trial-level selection-period returns.

    ``validation_returns.csv`` is retained only as a compatibility filename.
    For strict-eval-manifest.v4, its semantic role is
    ``selection_period_returns``.

    V4 strict-identical assembly requires an explicit locked reference
    calendar plus the exact evaluation specification bound into the manifest.
    It never infers the reference calendar from the first successful trial.

    Legacy manifests retain the historical first-trial fallback so existing
    callers remain backward compatible.
    """
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = Path(eval_dir)

    strict_v4 = manifest.get("schema") == "agent-alpha-audit.strict-eval-manifest.v4"

    if strict_v4 and require_identical_dates:
        if reference_calendar_csv is None:
            raise ValueError(
                "strict-eval-manifest.v4 requires reference_calendar_csv for identical-date assembly"
            )
        if evaluation_spec_path is None:
            raise ValueError(
                "strict-eval-manifest.v4 requires evaluation_spec_path for selection-period assembly"
            )

    semantic_name = "legacy_unspecified_return_series"
    compatibility_filename = "validation_returns.csv"
    selection_start = None
    selection_end = None
    spec_file_sha256 = None

    if evaluation_spec_path is not None:
        spec_path = Path(evaluation_spec_path)
        spec = json.loads(spec_path.read_text(encoding="utf-8"))

        if spec.get("schema") != ("agent-alpha-audit.rdagent-evaluation-spec.v1"):
            raise ValueError("unexpected evaluation specification schema")

        spec_file_sha256 = sha256_file(spec_path)

        if strict_v4:
            bound_spec = manifest.get("evidence", {}).get("evaluation_spec", {})

            expected_file_sha = bound_spec.get("file_sha256")
            expected_spec_sha = bound_spec.get("spec_sha256")

            if not expected_file_sha:
                raise ValueError("v4 manifest lacks bound evaluation-spec file hash")

            if expected_file_sha != spec_file_sha256:
                raise ValueError("evaluation specification file hash does not match v4 manifest binding")

            if expected_spec_sha and expected_spec_sha != spec.get("spec_sha256"):
                raise ValueError("evaluation specification semantic hash does not match v4 manifest binding")

        try:
            selection = spec["periods"]["agent_visible_selection"]
            output_contract = spec["phases"]["strict_selection_replay"]["required_trial_output"]
        except KeyError as exc:
            raise ValueError("evaluation specification lacks locked selection-period contract") from exc

        semantic_name = output_contract.get("semantic_name")
        compatibility_filename = output_contract.get("compatibility_filename")

        if semantic_name != "selection_period_returns":
            raise ValueError(
                "strict selection replay output must have semantic_name='selection_period_returns'"
            )

        if compatibility_filename != "validation_returns.csv":
            raise ValueError("unexpected strict selection replay compatibility filename")

        selection_start = pd.Timestamp(selection["start"])
        selection_end = pd.Timestamp(selection["end"])

        if selection_start > selection_end:
            raise ValueError("invalid locked selection-period bounds")

    reference_index: pd.DatetimeIndex | None = None
    reference_source = None
    reference_calendar_sha256 = None

    if reference_calendar_csv is not None:
        calendar_path = Path(reference_calendar_csv)

        if not calendar_path.is_file():
            raise ValueError("reference calendar file does not exist")

        calendar_df = pd.read_csv(calendar_path)

        if "date" not in calendar_df.columns:
            raise ValueError("reference calendar must contain a date column")

        parsed = pd.to_datetime(
            calendar_df["date"],
            errors="coerce",
        )

        if parsed.isna().any():
            raise ValueError("reference calendar contains invalid dates")

        reference_index = pd.DatetimeIndex(parsed)

        if reference_index.empty:
            raise ValueError("reference calendar is empty")

        if reference_index.has_duplicates:
            raise ValueError("reference calendar contains duplicate dates")

        if not reference_index.is_monotonic_increasing:
            raise ValueError("reference calendar must be strictly chronological")

        if selection_start is not None and reference_index.min() < selection_start:
            raise ValueError("reference calendar begins before locked selection period")

        if selection_end is not None and reference_index.max() > selection_end:
            raise ValueError("reference calendar ends after locked selection period")

        reference_source = "explicit_locked_calendar"
        reference_calendar_sha256 = sha256_file(calendar_path)

    series: list[pd.Series] = []
    details: list[dict[str, Any]] = []

    items = manifest.get(
        "trial_items",
        manifest.get("items", []),
    )

    for item in items:
        tid = str(item["trial_id"])

        if strict_v4 and not item.get(
            "strict_replay_ready",
            False,
        ):
            details.append(
                {
                    "trial_id": tid,
                    "status": "not_strict_replay_ready",
                }
            )
            continue

        p = root / f"trial_{tid}" / compatibility_filename

        if not p.exists():
            details.append(
                {
                    "trial_id": tid,
                    "status": "missing_returns",
                }
            )
            continue

        df = pd.read_csv(p)

        if not {"date", "return"}.issubset(df.columns):
            details.append(
                {
                    "trial_id": tid,
                    "status": "invalid_schema",
                }
            )
            continue

        dates = pd.to_datetime(
            df["date"],
            errors="coerce",
        )

        values = pd.to_numeric(
            df["return"],
            errors="coerce",
        )

        if dates.isna().any():
            details.append(
                {
                    "trial_id": tid,
                    "status": "invalid_dates",
                }
            )
            continue

        s = pd.Series(
            values.values,
            index=dates,
            name=f"trial_{tid}",
        )

        s = s[~s.index.duplicated(keep="last")].sort_index().dropna()

        trial_index = pd.DatetimeIndex(s.index)

        if require_identical_dates and reference_index is None:
            # Legacy-only behavior. V4 cannot reach this
            # branch because it requires an explicit
            # reference_calendar_csv above.
            reference_index = trial_index
            reference_source = "legacy_first_included_trial"

        elif require_identical_dates and not trial_index.equals(reference_index):
            raise ValueError(f"trial {tid} return dates differ from the locked reference calendar")

        series.append(s)

        details.append(
            {
                "trial_id": tid,
                "status": "included",
                "sha256": sha256_file(p),
                "n": int(s.size),
                "start": (s.index.min().date().isoformat() if len(s) else None),
                "end": (s.index.max().date().isoformat() if len(s) else None),
            }
        )

    aligned = (
        pd.concat(
            series,
            axis=1,
            join=("inner" if require_identical_dates else "outer"),
        ).sort_index()
        if series
        else pd.DataFrame()
    )

    aligned.index.name = "date"
    aligned.to_csv(out_csv)

    raw_n = int(
        manifest.get(
            "raw_trials_lower_bound",
            len(items),
        )
    )
    included = len(series)

    summary = {
        "schema": "agent-alpha-audit.return-coverage.v3",
        "return_semantic_name": semantic_name,
        "compatibility_filename": (compatibility_filename),
        "raw_trials_lower_bound": raw_n,
        "trials_with_aligned_returns": included,
        "coverage": (included / raw_n if raw_n else 0.0),
        "date_alignment_policy": (
            "locked_reference_calendar"
            if (require_identical_dates and reference_source == "explicit_locked_calendar")
            else ("strict_identical" if require_identical_dates else "outer_union")
        ),
        "reference_calendar_source": (reference_source),
        "reference_calendar_sha256": (reference_calendar_sha256),
        "reference_calendar_n": (len(reference_index) if reference_index is not None else 0),
        "reference_calendar_start": (
            reference_index.min().date().isoformat()
            if (reference_index is not None and len(reference_index))
            else None
        ),
        "reference_calendar_end": (
            reference_index.max().date().isoformat()
            if (reference_index is not None and len(reference_index))
            else None
        ),
        "selection_period_start": (
            selection_start.date().isoformat() if selection_start is not None else None
        ),
        "selection_period_end": (selection_end.date().isoformat() if selection_end is not None else None),
        "evaluation_spec_file_sha256": (spec_file_sha256),
        "aligned_n": len(aligned),
        "aligned_start": (aligned.index.min().date().isoformat() if len(aligned) else None),
        "aligned_end": (aligned.index.max().date().isoformat() if len(aligned) else None),
        "output": str(out_csv),
        "details": details,
    }

    if coverage_json:
        Path(coverage_json).write_text(
            json.dumps(
                summary,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    return summary
