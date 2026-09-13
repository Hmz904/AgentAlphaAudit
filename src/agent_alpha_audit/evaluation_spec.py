from __future__ import annotations

import hashlib
import json
from importlib import metadata
from pathlib import Path
from typing import Any

import yaml

SCHEMA = "agent-alpha-audit.rdagent-evaluation-spec.v1"
PRIMARY_CONFIG = "conf_combined_factors.yaml"


class EvaluationSpecError(ValueError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return _sha256_bytes(payload)


def _iso(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _single_run_config(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    configs = [row for row in rows if row.get("tag") == "run_config"]

    if len(configs) != 1:
        raise EvaluationSpecError(f"expected one canonical run_config, found {len(configs)}")

    return configs[0]


def _runtime_configs(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("tag") == "runtime_qlib_config"]


def _validate_runtime_configs(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    events = _runtime_configs(rows)

    if not events:
        raise EvaluationSpecError("no runtime_qlib_config events observed")

    payloads = [row.get("payload") or {} for row in events]

    names = {str(payload.get("config_name")) for payload in payloads}
    hashes = {str(payload.get("config_sha256")) for payload in payloads}
    statuses = {str(payload.get("status")) for payload in payloads}

    if names != {PRIMARY_CONFIG}:
        raise EvaluationSpecError(f"unexpected runtime config names: {sorted(names)}")

    if len(hashes) != 1 or "" in hashes or "None" in hashes:
        raise EvaluationSpecError(f"runtime config hash drift: {sorted(hashes)}")

    if statuses != {"match"}:
        raise EvaluationSpecError(f"runtime config status mismatch: {sorted(statuses)}")

    paths = [Path(str(payload["config_path"])) for payload in payloads if payload.get("config_path")]

    if not paths:
        raise EvaluationSpecError("runtime config path unavailable")

    existing = [path for path in paths if path.is_file()]

    if not existing:
        raise EvaluationSpecError("no surviving runtime primary config file")

    expected_hash = next(iter(hashes))

    usable = [path for path in existing if _sha256_file(path) == expected_hash]

    if not usable:
        raise EvaluationSpecError("surviving runtime config does not match captured SHA256")

    return {
        "observed_count": len(events),
        "name": PRIMARY_CONFIG,
        "sha256": expected_hash,
        "config_path": usable[-1],
    }


def _package_versions() -> dict[str, str]:
    out = {}

    for package in (
        "pyqlib",
        "lightgbm",
        "pandas",
        "numpy",
    ):
        try:
            out[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            out[package] = "not-installed"

    return out


def _loader_class(loader: dict[str, Any]) -> str:
    return str(loader.get("class") or "")


def _processor_names(
    processors: list[dict[str, Any]] | None,
) -> list[str]:
    return [str(item.get("class")) for item in processors or [] if isinstance(item, dict)]


def _extract_primary_semantics(
    config: dict[str, Any],
) -> dict[str, Any]:
    qlib_init = config.get("qlib_init") or {}
    handler = config.get("data_handler_config") or {}
    task = config.get("task") or {}
    dataset = task.get("dataset") or {}
    model = task.get("model") or {}
    port = config.get("port_analysis_config") or {}
    strategy = port.get("strategy") or {}
    backtest = port.get("backtest") or {}
    exchange = backtest.get("exchange_kwargs") or {}

    data_loader = handler.get("data_loader") or {}
    loader_kwargs = data_loader.get("kwargs") or {}
    loaders = loader_kwargs.get("dataloader_l") or []

    if len(loaders) != 2:
        raise EvaluationSpecError("primary config must contain exactly Alpha158DL + StaticDataLoader")

    alpha_loader = loaders[0]
    static_loader = loaders[1]

    if _loader_class(alpha_loader) != ("qlib.contrib.data.loader.Alpha158DL"):
        raise EvaluationSpecError("first primary loader is not Alpha158DL")

    if _loader_class(static_loader) != ("qlib.data.dataset.loader.StaticDataLoader"):
        raise EvaluationSpecError("second primary loader is not StaticDataLoader")

    alpha_cfg = (alpha_loader.get("kwargs") or {}).get("config") or {}

    labels = alpha_cfg.get("label") or []

    if len(labels) != 2 or not labels[0] or not labels[1]:
        raise EvaluationSpecError("unexpected label structure")

    label_expression = str(labels[0][0])
    label_name = str(labels[1][0])

    expected_label = "Ref($close, -2)/Ref($close, -1) - 1"

    if label_expression.replace(" ", "") != expected_label.replace(" ", ""):
        raise EvaluationSpecError(f"unexpected label expression: {label_expression}")

    features = alpha_cfg.get("feature") or []

    if len(features) != 2:
        raise EvaluationSpecError("unexpected baseline feature structure")

    expressions = [str(x) for x in features[0]]
    names = [str(x) for x in features[1]]

    if len(expressions) != len(names):
        raise EvaluationSpecError("baseline feature expression/name mismatch")

    segments = (dataset.get("kwargs") or {}).get("segments") or {}

    return {
        "qlib_region": str(qlib_init.get("region")),
        "template_provider_uri": str(qlib_init.get("provider_uri")),
        "market": str(config.get("market")),
        "benchmark": str(config.get("benchmark")),
        "handler": {
            "start_time": _iso(handler.get("start_time")),
            "end_time": _iso(handler.get("end_time")),
        },
        "label": {
            "name": label_name,
            "expression": label_expression,
            "semantic": ("at prediction date t: close[t+2] / close[t+1] - 1"),
        },
        "baseline_features": {
            "loader": ("qlib.contrib.data.loader.Alpha158DL"),
            "count": len(names),
            "names": names,
            "expressions": expressions,
        },
        "recovered_factor_loader": {
            "class": ("qlib.data.dataset.loader.StaticDataLoader"),
            "config": str((static_loader.get("kwargs") or {}).get("config")),
        },
        "processors": {
            "infer": _processor_names(handler.get("infer_processors")),
            "learn": _processor_names(handler.get("learn_processors")),
        },
        "dataset": {
            "class": str(dataset.get("class")),
            "module_path": str(dataset.get("module_path")),
            "segments": {key: [_iso(v) for v in value] for key, value in segments.items()},
        },
        "model": {
            "class": str(model.get("class")),
            "module_path": str(model.get("module_path")),
            "configured_kwargs": (model.get("kwargs") or {}),
        },
        "strategy": {
            "class": str(strategy.get("class")),
            "module_path": str(strategy.get("module_path")),
            "kwargs": (strategy.get("kwargs") or {}),
        },
        "backtest": {
            "start_time": _iso(backtest.get("start_time")),
            "end_time": _iso(backtest.get("end_time")),
            "account": backtest.get("account"),
            "benchmark": str(backtest.get("benchmark")),
            "exchange_kwargs": exchange,
        },
    }


def build_rdagent_evaluation_spec(
    *,
    logical_events: Path,
    artifact_manifest: Path,
    out_path: Path,
    runtime_versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    rows = _load_jsonl(logical_events)

    run_event = _single_run_config(rows)
    run_payload = run_event.get("payload") or {}
    lock = run_payload.get("run_lock") or {}

    if lock.get("status") != "LOCKED":
        raise EvaluationSpecError("run lock is not LOCKED")

    runtime = _validate_runtime_configs(rows)

    config = yaml.safe_load(runtime["config_path"].read_text(encoding="utf-8"))

    semantics = _extract_primary_semantics(config)

    artifacts = json.loads(artifact_manifest.read_text(encoding="utf-8"))

    if artifacts.get("schema") != ("agent-alpha-audit.artifact-recovery.v1"):
        raise EvaluationSpecError("unexpected artifact recovery schema")

    versions = runtime_versions if runtime_versions is not None else _package_versions()

    # Locked semantic checks against the run configuration.
    if semantics["market"].lower() != (str(lock["universe"]).lower()):
        raise EvaluationSpecError("runtime market disagrees with run lock")

    expected_segments = {
        "train": [
            str(lock["train_start"]),
            str(lock["train_end"]),
        ],
        "valid": [
            str(lock["validation_start"]),
            str(lock["validation_end"]),
        ],
        "test": [
            str(lock["agent_visible_test_start"]),
            str(lock["agent_visible_test_end"]),
        ],
    }

    if semantics["dataset"]["segments"] != expected_segments:
        raise EvaluationSpecError("runtime dataset segments disagree with run lock")

    exchange = semantics["backtest"]["exchange_kwargs"]

    upstream_open = float(exchange["open_cost"])
    upstream_close = float(exchange["close_cost"])

    strict_one_way = float(lock["one_way_cost_bps"]) / 10000.0

    strict_determinism = {
        "policy": "evaluator_side_control",
        "reason": ("upstream primary config contains no explicit LightGBM seed or deterministic flag"),
        "required_model_overrides": {
            "deterministic": True,
            "force_col_wise": True,
        },
        "seed_policy": (
            "preserve LightGBM defaults under pinned "
            "LightGBM version; do not claim an upstream "
            "user-specified seed"
        ),
    }

    periods = {
        "train": {
            "start": str(lock["train_start"]),
            "end": str(lock["train_end"]),
            "role": "model_fit",
        },
        "model_validation": {
            "start": str(lock["validation_start"]),
            "end": str(lock["validation_end"]),
            "role": ("early_stopping_and_model_validation"),
        },
        "agent_visible_selection": {
            "start": str(lock["agent_visible_test_start"]),
            "end": str(lock["agent_visible_test_end"]),
            "role": ("adaptive_search_selection_period; trial return series for DSR/search correction"),
        },
        "frozen_oos": {
            "start": str(lock["frozen_oos_start"]),
            "end": str(lock["frozen_oos_end"]),
            "role": ("never_agent_visible_primary_holdout"),
        },
    }

    spec: dict[str, Any] = {
        "schema": SCHEMA,
        "status": ("GLOBAL_EVALUATION_SPEC_READY_ITEM_BINDING_PENDING"),
        "primary_outcome_unit": str(lock["primary_outcome_unit"]),
        "evidence": {
            "rdagent_version": str(lock["rdagent_version"]),
            "rdagent_commit": str(lock["rdagent_commit"]),
            "runtime_primary_config": {
                "name": runtime["name"],
                "sha256": runtime["sha256"],
                "observed_runner_count": runtime["observed_count"],
                "status": "match",
            },
            "artifact_recovery": {
                "schema": artifacts["schema"],
                "manifest_sha256": _sha256_file(artifact_manifest),
                "artifact_tree_sha256": artifacts["artifact_tree_sha256"],
                "recovered_artifact_count": (artifacts["summary"]["recovered_artifact_count"]),
                "final_library_factor_count": (artifacts["summary"]["final_cumulative_library_factor_count"]),
            },
            "evaluator_runtime_versions": versions,
        },
        "provider_identity": {
            "research": {
                "role": ("physically_truncated_agent_visible_provider"),
                "snapshot_sha256": str(lock["qlib_data_snapshot_sha256"]),
                "calendar_sha256": str(
                    (run_payload.get("physical_data_cutoff") or {}).get("calendar_sha256")
                ),
                "last_trading_day": str(lock["research_provider_last_trading_day"]),
                "future_market_data_excluded": True,
            },
            "strict_full_history": {
                "role": ("strict_evaluator_full_history_provider"),
                "snapshot_sha256": str(lock["strict_eval_data_snapshot_sha256"]),
                "frozen_oos_end": str(lock["frozen_oos_end"]),
            },
        },
        "universe": {
            "region": semantics["qlib_region"],
            "market": semantics["market"],
            "benchmark": semantics["benchmark"],
        },
        "periods": periods,
        "data_semantics": {
            "label": semantics["label"],
            "baseline_features": semantics["baseline_features"],
            "recovered_factor_loader": semantics["recovered_factor_loader"],
            "processors": semantics["processors"],
            "original_handler_window": semantics["handler"],
        },
        "combination_model": {
            **semantics["model"],
            "effective_defaults_from_pyqlib_0_9_7": {
                "early_stopping_rounds": 50,
                "num_boost_round": 1000,
            },
            "upstream_explicit_seed": False,
            "upstream_explicit_deterministic_flag": False,
        },
        "portfolio": {
            "strategy": semantics["strategy"],
            "account": semantics["backtest"]["account"],
            "execution": {
                "signal_lag_steps": 1,
                "prediction_step": "t",
                "trade_step": "t+1",
                "deal_price": str(exchange["deal_price"]),
                "limit_threshold": float(exchange["limit_threshold"]),
                "min_cost": float(exchange["min_cost"]),
                "timing_source": (
                    "pyqlib 0.9.7 "
                    "TopkDropoutStrategy.generate_trade_decision: "
                    "get_step_time(trade_step, shift=1)"
                ),
            },
        },
        "phases": {
            "upstream_reproduction": {
                "purpose": ("compatibility check against captured RD-Agent/Qlib results"),
                "provider": "research",
                "train_period": "train",
                "validation_period": "model_validation",
                "test_period": "agent_visible_selection",
                "model_policy": ("preserve captured upstream model configuration and library defaults"),
                "costs": {
                    "open_cost": upstream_open,
                    "close_cost": upstream_close,
                    "round_trip_nominal": (upstream_open + upstream_close),
                },
                "deterministic_claim": False,
            },
            "strict_selection_replay": {
                "purpose": (
                    "deterministic search-accounting returns "
                    "for trial Sharpe dispersion, DSR and "
                    "redundancy diagnostics"
                ),
                "provider": "research",
                "train_period": "train",
                "validation_period": "model_validation",
                "test_period": "agent_visible_selection",
                "costs": {
                    "open_cost": strict_one_way,
                    "close_cost": strict_one_way,
                    "round_trip_nominal": (2.0 * strict_one_way),
                },
                "determinism": strict_determinism,
                "required_trial_output": {
                    "semantic_name": ("selection_period_returns"),
                    "compatibility_filename": ("validation_returns.csv"),
                    "columns": ["date", "return"],
                    "date_support": ("locked agent-visible selection calendar, identical across trials"),
                },
            },
            "strict_frozen_oos": {
                "purpose": ("primary never-agent-visible generalization evaluation"),
                "provider": "strict_full_history",
                "train_period": "train",
                "validation_period": "model_validation",
                "test_period": "frozen_oos",
                "handler_end_time_override": str(lock["frozen_oos_end"]),
                "reason_for_handler_override": (
                    "captured primary YAML ends its data "
                    "handler at 2022-08-01, before the locked "
                    "frozen OOS end; the strict evaluator must "
                    "extend only the handler/test horizon, "
                    "without changing training or validation"
                ),
                "costs": {
                    "open_cost": strict_one_way,
                    "close_cost": strict_one_way,
                    "round_trip_nominal": (2.0 * strict_one_way),
                },
                "determinism": strict_determinism,
                "required_primary_output": {
                    "filename": ("frozen_oos_returns.csv"),
                    "columns": ["date", "return"],
                },
            },
        },
        "binding_requirements": {
            "global_spec_complete": True,
            "trial_artifact_composition_bound": False,
            "cumulative_library_artifacts_bound": False,
            "strict_replay_ready_must_remain_false": True,
            "next_step": (
                "bind recovered immutable artifacts to each "
                "trial experiment and each observed cumulative "
                "library state before changing strict replay "
                "readiness"
            ),
        },
    }

    spec["spec_sha256"] = _canonical_sha256(spec)

    serialized = (
        json.dumps(
            spec,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )

    if "/home/" in serialized:
        raise EvaluationSpecError("evaluation spec leaks an absolute home path")

    out_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    out_path.write_text(
        serialized,
        encoding="utf-8",
    )

    return spec
