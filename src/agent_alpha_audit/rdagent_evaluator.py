from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

VALID_UNITS = {
    "trial_experiment",
    "cumulative_factor_library_at_loop_k",
}

VALID_PHASES = {
    "strict_selection_replay",
    "strict_frozen_oos",
}


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def selection_returns_semantic_sha256(
    dates: pd.DatetimeIndex,
    returns: Any,
    decimal_places: int = 12,
) -> str:
    """Return a digest stable to machine-precision float noise.

    Raw return files remain unrounded and retain their raw SHA256.
    Canonicalization is only a reproducibility-comparison layer.
    """
    values = pd.Series(
        returns,
        dtype="float64",
    ).to_numpy()

    if len(dates) != len(values):
        raise ValueError("dates and returns have different lengths")

    h = hashlib.sha256()

    for date, value in zip(
        dates,
        values,
        strict=True,
    ):
        line = f"{pd.Timestamp(date).strftime('%Y-%m-%d')},{float(value):.{decimal_places}f}\n"
        h.update(line.encode("utf-8"))

    return h.hexdigest()


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_request(
    request: dict[str, Any],
    artifact_root: str | Path,
    evaluation_spec_path: str | Path,
) -> list[dict[str, Any]]:
    if request.get("evaluation_unit") not in VALID_UNITS:
        raise ValueError(f"unexpected evaluation_unit: {request.get('evaluation_unit')!r}")

    if not request.get("strict_replay_ready"):
        raise ValueError("request is not strict_replay_ready")

    if not request.get("evaluable"):
        raise ValueError("request is not evaluable")

    spec_ref = request.get("evaluation_spec", {})
    if not spec_ref.get("verified"):
        raise ValueError("request evaluation-spec binding is not verified")

    spec_path = Path(evaluation_spec_path)
    spec = _load_json(spec_path)

    if spec.get("schema") != "agent-alpha-audit.rdagent-evaluation-spec.v1":
        raise ValueError("unexpected evaluation specification schema")

    actual_spec_file_sha = sha256_file(spec_path)
    expected_spec_file_sha = spec_ref.get("file_sha256")

    if expected_spec_file_sha != actual_spec_file_sha:
        raise ValueError("evaluation specification file hash does not match request binding")

    expected_semantic_sha = spec_ref.get("spec_sha256")
    if expected_semantic_sha and expected_semantic_sha != spec.get("spec_sha256"):
        raise ValueError("evaluation specification semantic hash does not match request binding")

    binding = request.get("composition_binding", {})
    if not binding.get("verified"):
        raise ValueError("composition binding is not verified")

    impl = request.get("implementation_artifact", {})
    if not impl.get("artifact_hashes_verified"):
        raise ValueError("implementation artifact hashes are not verified")

    artifacts = impl.get("artifacts", [])
    if not artifacts:
        raise ValueError("request contains no implementation artifacts")

    if impl.get("artifact_count") != len(artifacts):
        raise ValueError("artifact_count does not match artifact list")

    root = Path(artifact_root)

    names: set[str] = set()

    for i, artifact in enumerate(artifacts):
        name = artifact.get("name")
        rel = artifact.get("relative_path")
        expected_sha = artifact.get("sha256")

        if not name or not rel or not expected_sha:
            raise ValueError(f"artifact {i} lacks name, relative_path, or sha256")

        if name in names:
            raise ValueError(f"duplicate factor name in bound composition: {name}")
        names.add(name)

        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise ValueError(f"unsafe artifact relative_path: {rel}")

        source = root / rel_path

        if not source.is_file():
            raise ValueError(f"bound artifact is missing: {rel}")

        actual_sha = sha256_file(source)

        if actual_sha != expected_sha:
            raise ValueError(f"artifact hash mismatch for {name}: expected {expected_sha}, got {actual_sha}")

    return artifacts


def _validate_factor_frame(
    df: pd.DataFrame,
    factor_name: str,
) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"{factor_name}: result.h5 did not contain a DataFrame")

    if not isinstance(df.index, pd.MultiIndex):
        raise TypeError(f"{factor_name}: factor result index is not MultiIndex")

    if not {"datetime", "instrument"}.issubset(df.index.names):
        raise ValueError(
            f"{factor_name}: factor result index names are {df.index.names}, expected datetime/instrument"
        )

    if factor_name not in df.columns:
        raise ValueError(f"{factor_name}: expected output column is absent; columns={list(df.columns)}")

    if len(df.columns) != 1:
        raise ValueError(f"{factor_name}: expected exactly one output column; columns={list(df.columns)}")

    return df[[factor_name]]


def execute_factor(
    artifact: dict[str, Any],
    artifact_root: str | Path,
    daily_pv_path: str | Path,
    factor_run_root: str | Path,
    timeout_seconds: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    name = str(artifact["name"])
    source = Path(artifact_root) / artifact["relative_path"]
    run_dir = Path(factor_run_root) / (f"{int(artifact['slot_index']):02d}__{name}")
    run_dir.mkdir(parents=True, exist_ok=True)

    factor_dst = run_dir / "factor.py"
    daily_dst = run_dir / "daily_pv.h5"
    result_path = run_dir / "result.h5"

    shutil.copy2(source, factor_dst)

    if daily_dst.exists() or daily_dst.is_symlink():
        daily_dst.unlink()

    os.symlink(
        Path(daily_pv_path).resolve(),
        daily_dst,
    )

    if result_path.exists():
        result_path.unlink()

    started = time.perf_counter()

    try:
        proc = subprocess.run(
            [sys.executable, "factor.py"],
            cwd=run_dir,
            text=True,
            capture_output=True,
            timeout=int(timeout_seconds),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.perf_counter() - started
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")

        (run_dir / "stdout.txt").write_text(
            stdout,
            encoding="utf-8",
        )
        (run_dir / "stderr.txt").write_text(
            stderr,
            encoding="utf-8",
        )

        raise RuntimeError(f"factor_timeout:{name}:{duration:.3f}s") from exc

    duration = time.perf_counter() - started

    (run_dir / "stdout.txt").write_text(
        proc.stdout or "",
        encoding="utf-8",
    )
    (run_dir / "stderr.txt").write_text(
        proc.stderr or "",
        encoding="utf-8",
    )

    if proc.returncode != 0:
        raise RuntimeError(f"factor_execution_failed:{name}:returncode={proc.returncode}")

    if not result_path.is_file():
        raise RuntimeError(f"factor_missing_result:{name}")

    df = pd.read_hdf(
        result_path,
        key="data",
    )
    df = _validate_factor_frame(
        df,
        name,
    )

    meta = {
        "name": name,
        "source_sha256": artifact["sha256"],
        "result_sha256": sha256_file(result_path),
        "rows": len(df),
        "non_null": int(df[name].notna().sum()),
        "duration_seconds": round(duration, 6),
        "returncode": int(proc.returncode),
        "status": "ok",
    }

    return df, meta


def combine_factor_frames(
    frames: list[pd.DataFrame],
) -> pd.DataFrame:
    if not frames:
        raise ValueError("no factor frames to combine")

    # RD-Agent QlibFactorRunner semantics:
    #   pd.concat(..., axis=1).dropna()
    #   sort_index()
    #   duplicate columns keep="last"
    #   MultiIndex columns under "feature".
    combined = pd.concat(
        frames,
        axis=1,
    ).dropna()

    combined = combined.sort_index()

    combined = combined.loc[
        :,
        ~combined.columns.duplicated(keep="last"),
    ]

    combined.columns = pd.MultiIndex.from_product(
        [
            ["feature"],
            list(combined.columns),
        ]
    )

    return combined


def _period(
    spec: dict[str, Any],
    name: str,
) -> tuple[str, str]:
    p = spec["periods"][name]
    return str(p["start"]), str(p["end"])


def _set_static_loader_config(obj: Any) -> int:
    """Rewrite StaticDataLoader config, counting each YAML object once.

    PyYAML preserves aliases as shared Python objects.  The captured RD-Agent
    config exposes ``data_handler_config`` both at the top level and again via
    the handler's YAML alias, so a naive recursive walk visits the same loader
    twice.  Object-identity tracking preserves the YAML graph semantics.
    """
    seen: set[int] = set()

    def visit(value: Any) -> int:
        if isinstance(value, (dict, list)):
            ident = id(value)
            if ident in seen:
                return 0
            seen.add(ident)

        count = 0

        if isinstance(value, dict):
            cls = value.get("class")

            if isinstance(cls, str) and cls.endswith("StaticDataLoader"):
                kwargs = value.setdefault("kwargs", {})
                kwargs["config"] = "combined_factors_df.parquet"
                count += 1

            for child in value.values():
                count += visit(child)

        elif isinstance(value, list):
            for child in value:
                count += visit(child)

        return count

    return visit(obj)


def build_strict_config(
    template_config_path: str | Path,
    evaluation_spec_path: str | Path,
    provider_path: str | Path,
    phase_name: str,
) -> dict[str, Any]:
    if phase_name not in VALID_PHASES:
        raise ValueError(f"unexpected strict phase: {phase_name}")

    template_path = Path(template_config_path)

    cfg = yaml.safe_load(template_path.read_text(encoding="utf-8"))

    spec = _load_json(evaluation_spec_path)

    phase = spec["phases"][phase_name]

    cfg["qlib_init"]["provider_uri"] = str(Path(provider_path).resolve())

    train_start, train_end = _period(
        spec,
        phase["train_period"],
    )
    valid_start, valid_end = _period(
        spec,
        phase["validation_period"],
    )
    test_start, test_end = _period(
        spec,
        phase["test_period"],
    )

    segments = cfg["task"]["dataset"]["kwargs"]["segments"]

    segments["train"] = [
        train_start,
        train_end,
    ]
    segments["valid"] = [
        valid_start,
        valid_end,
    ]
    segments["test"] = [
        test_start,
        test_end,
    ]

    backtest = cfg["port_analysis_config"]["backtest"]

    backtest["start_time"] = test_start
    backtest["end_time"] = test_end
    backtest["exchange_kwargs"]["open_cost"] = float(phase["costs"]["open_cost"])
    backtest["exchange_kwargs"]["close_cost"] = float(phase["costs"]["close_cost"])

    model_kwargs = cfg["task"]["model"].setdefault("kwargs", {})

    for key, value in phase["determinism"]["required_model_overrides"].items():
        model_kwargs[key] = value

    if phase_name == "strict_frozen_oos":
        cfg["data_handler_config"]["end_time"] = str(phase["handler_end_time_override"])

    static_count = _set_static_loader_config(cfg)

    if static_count != 1:
        raise ValueError(f"expected exactly one StaticDataLoader in strict config, found {static_count}")

    # Make the PortAnaRecord use the same mutated
    # top-level backtest configuration even if YAML
    # alias identity is not preserved by a parser.
    records = cfg["task"].get(
        "record",
        [],
    )

    port_record_count = 0

    for record in records:
        cls = str(record.get("class", ""))

        if cls.endswith("PortAnaRecord"):
            record.setdefault(
                "kwargs",
                {},
            )["config"] = cfg["port_analysis_config"]
            port_record_count += 1

    if port_record_count != 1:
        raise ValueError(f"expected exactly one PortAnaRecord, found {port_record_count}")

    return cfg


def write_yaml(
    obj: dict[str, Any],
    path: str | Path,
) -> None:
    Path(path).write_text(
        yaml.safe_dump(
            obj,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def prepare_strict_evaluation(
    *,
    request_path: str | Path,
    out_dir: str | Path,
    artifact_root: str | Path,
    evaluation_spec_path: str | Path,
    template_config_path: str | Path,
    provider_path: str | Path,
    daily_pv_path: str | Path,
    phase_name: str,
    expected_template_sha256: str | None = None,
    expected_daily_pv_sha256: str | None = None,
    execute_factors: bool = False,
    factor_timeout_seconds: int = 3600,
) -> dict[str, Any]:
    started = time.perf_counter()

    request = _load_json(request_path)

    artifacts = validate_request(
        request,
        artifact_root,
        evaluation_spec_path,
    )

    template_sha = sha256_file(template_config_path)
    daily_sha = sha256_file(daily_pv_path)

    if expected_template_sha256 and template_sha != expected_template_sha256:
        raise ValueError("template config hash mismatch")

    if expected_daily_pv_sha256 and daily_sha != expected_daily_pv_sha256:
        raise ValueError("daily_pv hash mismatch")

    root = Path(out_dir)
    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    cfg = build_strict_config(
        template_config_path,
        evaluation_spec_path,
        provider_path,
        phase_name,
    )

    config_path = root / "conf_strict.yaml"
    write_yaml(
        cfg,
        config_path,
    )

    factor_meta: list[dict[str, Any]] = []

    combined_rows = None
    combined_columns = None

    if execute_factors:
        frames = []
        factor_root = root / "factor_runs"
        factor_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        for artifact in artifacts:
            frame, meta = execute_factor(
                artifact,
                artifact_root,
                daily_pv_path,
                factor_root,
                factor_timeout_seconds,
            )
            frames.append(frame)
            factor_meta.append(meta)

        combined = combine_factor_frames(frames)

        combined_path = root / "combined_factors_df.parquet"

        combined.to_parquet(
            combined_path,
            engine="pyarrow",
        )

        combined_rows = len(combined)
        combined_columns = [str(x) for x in combined.columns.get_level_values(1)]

    result = {
        "schema": ("agent-alpha-audit.rdagent-strict-evaluator-preparation.v1"),
        "status": ("factor_outputs_ready" if execute_factors else "prepared"),
        "evaluation_unit": request["evaluation_unit"],
        "trial_id": request.get("trial_id"),
        "loop_k": request.get("loop_k"),
        "phase": phase_name,
        "strict_replay_completed": False,
        "qrun_completed": False,
        "factor_count": len(artifacts),
        "factor_names": [x["name"] for x in artifacts],
        "factor_results": factor_meta,
        "combined_rows": combined_rows,
        "combined_factor_columns": (combined_columns),
        "evidence": {
            "evaluation_spec_file_sha256": (sha256_file(evaluation_spec_path)),
            "template_config_sha256": (template_sha),
            "daily_pv_sha256": (daily_sha),
            "generated_config_sha256": (sha256_file(config_path)),
            "composition_sha256": (request["implementation_artifact"].get("composition_sha256")),
        },
        "duration_seconds": round(
            time.perf_counter() - started,
            6,
        ),
    }

    (root / "result.json").write_text(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return result


class StrictReplayError(RuntimeError):
    def __init__(self, failure_class: str, message: str) -> None:
        super().__init__(message)
        self.failure_class = failure_class


def _load_locked_calendar(path: str | Path) -> pd.DatetimeIndex:
    df = pd.read_csv(path)

    if df.empty:
        raise StrictReplayError(
            "calendar_invalid",
            "locked reference calendar is empty",
        )

    column = "date" if "date" in df.columns else df.columns[0]

    idx = pd.DatetimeIndex(pd.to_datetime(df[column]))

    if idx.has_duplicates:
        raise StrictReplayError(
            "calendar_invalid",
            "locked reference calendar contains duplicate dates",
        )

    if not idx.is_monotonic_increasing:
        raise StrictReplayError(
            "calendar_invalid",
            "locked reference calendar is not monotonic",
        )

    return idx


def finalize_selection_returns(
    *,
    ret_path: str | Path,
    qlib_metrics_path: str | Path,
    reference_calendar_csv: str | Path,
    out_csv: str | Path,
    contract_json: str | Path,
) -> dict[str, Any]:
    ret_path = Path(ret_path)
    metrics_path = Path(qlib_metrics_path)
    calendar_path = Path(reference_calendar_csv)
    out_csv = Path(out_csv)
    contract_json = Path(contract_json)

    ret = pd.read_pickle(ret_path)

    if not isinstance(ret, pd.DataFrame):
        raise StrictReplayError(
            "return_report_invalid",
            "ret.pkl does not contain a DataFrame",
        )

    required = {
        "account",
        "return",
        "cost",
        "bench",
    }
    missing = required.difference(ret.columns)

    if missing:
        raise StrictReplayError(
            "return_report_invalid",
            f"ret.pkl is missing required columns: {sorted(missing)}",
        )

    report_idx = pd.DatetimeIndex(pd.to_datetime(ret.index))
    locked_idx = _load_locked_calendar(calendar_path)

    if report_idx.has_duplicates:
        raise StrictReplayError(
            "calendar_mismatch",
            "Qlib return report contains duplicate dates",
        )

    if not report_idx.equals(locked_idx):
        missing_dates = locked_idx.difference(report_idx)
        extra_dates = report_idx.difference(locked_idx)

        raise StrictReplayError(
            "calendar_mismatch",
            "Qlib report does not exactly match locked selection calendar; "
            f"missing={len(missing_dates)}, extra={len(extra_dates)}",
        )

    gross = ret["return"].astype(float)
    cost = ret["cost"].astype(float)
    bench = ret["bench"].astype(float)
    net = gross - cost

    if net.isna().any():
        raise StrictReplayError(
            "return_report_invalid",
            "net portfolio return contains NaN",
        )

    account_growth = ret["account"].astype(float).pct_change()

    account_error = (account_growth.iloc[1:] - net.iloc[1:]).abs()

    max_account_error = float(account_error.max())

    if max_account_error >= 1e-10:
        raise StrictReplayError(
            "return_semantics_mismatch",
            f"account growth does not equal return-cost; max_abs_error={max_account_error}",
        )

    metrics = pd.read_csv(
        metrics_path,
        index_col=0,
    ).iloc[:, 0]

    required_metrics = {
        "1day.excess_return_without_cost.mean",
        "1day.excess_return_with_cost.mean",
    }

    missing_metrics = required_metrics.difference(metrics.index)

    if missing_metrics:
        raise StrictReplayError(
            "qlib_metrics_invalid",
            f"Qlib metrics missing required rows: {sorted(missing_metrics)}",
        )

    gross_excess = gross - bench
    net_excess = net - bench

    gross_metric_error = abs(
        float(gross_excess.mean()) - float(metrics["1day.excess_return_without_cost.mean"])
    )

    net_metric_error = abs(float(net_excess.mean()) - float(metrics["1day.excess_return_with_cost.mean"]))

    if gross_metric_error >= 1e-10:
        raise StrictReplayError(
            "return_semantics_mismatch",
            f"Qlib without-cost metric does not equal mean(return-bench); error={gross_metric_error}",
        )

    if net_metric_error >= 1e-10:
        raise StrictReplayError(
            "return_semantics_mismatch",
            f"Qlib with-cost metric does not equal mean(return-cost-bench); error={net_metric_error}",
        )

    official = pd.DataFrame(
        {
            "date": report_idx.strftime("%Y-%m-%d"),
            "return": net.to_numpy(),
        }
    )

    official.to_csv(
        out_csv,
        index=False,
    )

    semantic_sha256 = selection_returns_semantic_sha256(
        report_idx,
        net.to_numpy(),
        decimal_places=12,
    )

    contract = {
        "schema": ("agent-alpha-audit.selection-return-contract.v1"),
        "semantic_name": ("selection_period_returns"),
        "compatibility_filename": ("validation_returns.csv"),
        "definition": ("portfolio_report['return'] - portfolio_report['cost']"),
        "interpretation": ("daily portfolio return net of transaction costs"),
        "benchmark_adjusted": False,
        "numeric_reproducibility": {
            "comparison": "absolute_difference",
            "absolute_tolerance": 1e-12,
            "canonical_decimal_places": 12,
            "semantic_sha256": semantic_sha256,
            "note": (
                "Raw returns are never rounded. The semantic digest "
                "is only for reproducibility comparison across "
                "machine-precision floating-point variation."
            ),
        },
        "benchmark_role": (
            "benchmark is retained for Qlib diagnostics but is not "
            "subtracted from the strategy return series used for "
            "trial Sharpe / DSR"
        ),
        "rows": len(official),
        "first_date": str(report_idx.min().date()),
        "last_date": str(report_idx.max().date()),
        "locked_calendar_exact_match": True,
        "account_identity": {
            "formula": ("account.pct_change() == return - cost"),
            "max_abs_error": max_account_error,
        },
        "qlib_metric_identity": {
            "without_cost": {
                "formula": "return - bench",
                "error": gross_metric_error,
            },
            "with_cost": {
                "formula": ("return - cost - bench"),
                "error": net_metric_error,
            },
        },
        "sha256": {
            "ret.pkl": sha256_file(ret_path),
            "qlib_res.csv": sha256_file(metrics_path),
            "selection_calendar.csv": sha256_file(calendar_path),
            "validation_returns.csv": sha256_file(out_csv),
        },
    }

    contract_json.write_text(
        json.dumps(
            contract,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return {
        "selection_return_rows": len(official),
        "selection_return_first_date": (contract["first_date"]),
        "selection_return_last_date": (contract["last_date"]),
        "validation_returns_sha256": (contract["sha256"]["validation_returns.csv"]),
        "selection_return_contract_sha256": (sha256_file(contract_json)),
        "validation_returns_semantic_sha256": semantic_sha256,
    }


def _run_logged_process(
    *,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
    stage: str,
) -> float:
    started = time.perf_counter()

    try:
        with (
            stdout_path.open(
                "w",
                encoding="utf-8",
            ) as stdout_fh,
            stderr_path.open(
                "w",
                encoding="utf-8",
            ) as stderr_fh,
        ):
            proc = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                stdout=stdout_fh,
                stderr=stderr_fh,
                timeout=timeout_seconds,
                check=False,
            )

    except subprocess.TimeoutExpired as exc:
        duration = time.perf_counter() - started

        raise StrictReplayError(
            f"{stage}_timeout",
            f"{stage} exceeded {timeout_seconds}s after {duration:.3f}s",
        ) from exc

    duration = time.perf_counter() - started

    if proc.returncode != 0:
        raise StrictReplayError(
            f"{stage}_failed",
            f"{stage} exited with returncode={proc.returncode}",
        )

    return duration


def _finalize_qrun_phase_outputs(
    *,
    phase_name: str,
    ret_path: str | Path,
    metrics_path: str | Path,
    reference_calendar_csv: str | Path | None,
    root: str | Path,
) -> dict[str, Any]:
    """Finalize qrun outputs according to evaluation phase."""
    root = Path(root)

    if phase_name == "strict_selection_replay":
        if reference_calendar_csv is None:
            raise StrictReplayError(
                "selection_calendar_missing",
                "strict_selection_replay requires a reference calendar",
            )

        return finalize_selection_returns(
            ret_path=ret_path,
            qlib_metrics_path=metrics_path,
            reference_calendar_csv=reference_calendar_csv,
            out_csv=root / "validation_returns.csv",
            contract_json=(root / "selection_return_contract_v1.json"),
        )

    if phase_name == "strict_frozen_oos":
        return {
            "return_semantic_name": ("frozen_oos_portfolio_report"),
            "validation_returns_written": False,
            "selection_return_contract_written": False,
        }

    raise StrictReplayError(
        "unsupported_qrun_phase",
        f"unsupported qrun phase: {phase_name}",
    )


def run_strict_selection_qrun(
    *,
    out_dir: str | Path,
    template_config_path: str | Path,
    reference_calendar_csv: str | Path | None,
    qrun_timeout_seconds: int = 7200,
    phase_name: str = "strict_selection_replay",
) -> dict[str, Any]:
    root = Path(out_dir)

    config_path = root / "conf_strict.yaml"
    combined_path = root / "combined_factors_df.parquet"

    if not config_path.is_file():
        raise StrictReplayError(
            "qrun_input_missing",
            "conf_strict.yaml is missing",
        )

    if not combined_path.is_file():
        raise StrictReplayError(
            "qrun_input_missing",
            "combined_factors_df.parquet is missing",
        )

    template_config_path = Path(template_config_path)

    read_exp_res_source = template_config_path.parent / "read_exp_res.py"

    if not read_exp_res_source.is_file():
        raise StrictReplayError(
            "qrun_input_missing",
            f"read_exp_res.py is missing beside template config: {read_exp_res_source}",
        )

    qrun_dir = root / "qrun_workspace"

    if qrun_dir.exists():
        shutil.rmtree(qrun_dir)

    qrun_dir.mkdir(
        parents=True,
    )

    shutil.copy2(
        config_path,
        qrun_dir / "conf_strict.yaml",
    )

    shutil.copy2(
        read_exp_res_source,
        qrun_dir / "read_exp_res.py",
    )

    os.symlink(
        combined_path.resolve(),
        qrun_dir / "combined_factors_df.parquet",
    )

    env = os.environ.copy()
    env["MLFLOW_ALLOW_FILE_STORE"] = "true"

    provenance = {
        "schema": ("agent-alpha-audit.qrun-environment.v1"),
        "compatibility_overrides": {
            "MLFLOW_ALLOW_FILE_STORE": {
                "value": "true",
                "classification": ("evaluator_infrastructure_compatibility"),
                "purpose": (
                    "Permit Qlib/RD-Agent filesystem MLflow tracking "
                    "under the installed MLflow version; does not alter "
                    "model, data, portfolio, cost, or selection semantics."
                ),
            }
        },
        "versions": {
            "mlflow": (importlib.metadata.version("mlflow")),
            "pyqlib": (importlib.metadata.version("pyqlib")),
        },
        "inputs": {
            "conf_strict_sha256": (sha256_file(config_path)),
            "combined_factors_df_sha256": (sha256_file(combined_path)),
            "read_exp_res_sha256": (sha256_file(read_exp_res_source)),
            "evaluation_phase": phase_name,
            "selection_calendar_sha256": (
                sha256_file(reference_calendar_csv)
                if (phase_name == "strict_selection_replay" and reference_calendar_csv is not None)
                else None
            ),
        },
        "isolated_tracking_workspace": True,
    }

    environment_path = root / "qrun_environment.json"

    environment_path.write_text(
        json.dumps(
            provenance,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    qrun_duration = _run_logged_process(
        command=[
            "qrun",
            "conf_strict.yaml",
        ],
        cwd=qrun_dir,
        env=env,
        stdout_path=(root / "qrun.stdout.txt"),
        stderr_path=(root / "qrun.stderr.txt"),
        timeout_seconds=(qrun_timeout_seconds),
        stage="qrun",
    )

    extraction_duration = _run_logged_process(
        command=[
            sys.executable,
            "read_exp_res.py",
        ],
        cwd=qrun_dir,
        env=env,
        stdout_path=(root / "read_exp_res.stdout.txt"),
        stderr_path=(root / "read_exp_res.stderr.txt"),
        timeout_seconds=600,
        stage="qlib_result_extraction",
    )

    ret_source = qrun_dir / "ret.pkl"
    metrics_source = qrun_dir / "qlib_res.csv"

    if not ret_source.is_file():
        raise StrictReplayError(
            "qlib_result_missing",
            "qrun completed but ret.pkl is missing",
        )

    if not metrics_source.is_file():
        raise StrictReplayError(
            "qlib_result_missing",
            "qrun completed but qlib_res.csv is missing",
        )

    ret_path = root / "ret.pkl"
    metrics_path = root / "qlib_res.csv"

    shutil.copy2(
        ret_source,
        ret_path,
    )
    shutil.copy2(
        metrics_source,
        metrics_path,
    )

    return_summary = _finalize_qrun_phase_outputs(
        phase_name=phase_name,
        ret_path=ret_path,
        metrics_path=metrics_path,
        reference_calendar_csv=(reference_calendar_csv),
        root=root,
    )

    return {
        "qrun_completed": True,
        "strict_replay_completed": True,
        "qrun_duration_seconds": round(
            qrun_duration,
            6,
        ),
        "result_extraction_duration_seconds": round(
            extraction_duration,
            6,
        ),
        "qrun_environment_sha256": (sha256_file(environment_path)),
        "ret_pkl_sha256": (sha256_file(ret_path)),
        "qlib_res_sha256": (sha256_file(metrics_path)),
        **return_summary,
    }
