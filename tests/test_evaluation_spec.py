from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agent_alpha_audit.evaluation_spec import (
    EvaluationSpecError,
    build_rdagent_evaluation_spec,
)

PRIMARY_YAML = """\
qlib_init:
  provider_uri: "~/.qlib/qlib_data/cn_data"
  region: cn

market: csi300
benchmark: SH000300

data_handler_config:
  start_time: 2008-01-01
  end_time: 2022-08-01
  instruments: csi300
  data_loader:
    class: NestedDataLoader
    kwargs:
      dataloader_l:
        - class: qlib.contrib.data.loader.Alpha158DL
          kwargs:
            config:
              label:
                - ["Ref($close, -2)/Ref($close, -1) - 1"]
                - ["LABEL0"]
              feature:
                - ["Ref($close, 1)/$close", "Std($close, 5)/$close"]
                - ["ROC", "STD"]
        - class: qlib.data.dataset.loader.StaticDataLoader
          kwargs:
            config: combined_factors_df.parquet
  learn_processors:
    - class: DropnaLabel
    - class: CSZScoreNorm
      kwargs:
        fields_group: label

port_analysis_config:
  strategy:
    class: TopkDropoutStrategy
    module_path: qlib.contrib.strategy
    kwargs:
      signal: "<PRED>"
      topk: 50
      n_drop: 5
  backtest:
    start_time: 2017-01-01
    end_time: 2020-08-01
    account: 100000000
    benchmark: SH000300
    exchange_kwargs:
      limit_threshold: 0.095
      deal_price: close
      open_cost: 0.0005
      close_cost: 0.0015
      min_cost: 5

task:
  model:
    class: LGBModel
    module_path: qlib.contrib.model.gbdt
    kwargs:
      loss: mse
      colsample_bytree: 0.8879
      learning_rate: 0.2
      subsample: 0.8789
      lambda_l1: 205.6999
      lambda_l2: 580.9768
      max_depth: 8
      num_leaves: 210
      num_threads: 20
  dataset:
    class: DatasetH
    module_path: qlib.data.dataset
    kwargs:
      handler:
        class: DataHandlerLP
        module_path: qlib.contrib.data.handler
      segments:
        train: [2008-01-01, 2014-12-31]
        valid: [2015-01-01, 2016-12-31]
        test: [2017-01-01, 2020-08-01]
"""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_jsonl(
    path: Path,
    rows: list[dict],
) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _run_config() -> dict:
    return {
        "trial_id": "__run__",
        "tag": "run_config",
        "payload": {
            "physical_data_cutoff": {
                "calendar_sha256": "calendar-sha",
            },
            "run_lock": {
                "status": "LOCKED",
                "universe": "CSI300",
                "train_start": "2008-01-01",
                "train_end": "2014-12-31",
                "validation_start": "2015-01-01",
                "validation_end": "2016-12-31",
                "agent_visible_test_start": ("2017-01-01"),
                "agent_visible_test_end": ("2020-08-01"),
                "frozen_oos_start": ("2020-08-03"),
                "frozen_oos_end": ("2026-09-10"),
                "one_way_cost_bps": 10.0,
                "primary_outcome_unit": ("cumulative_factor_library_at_loop_k"),
                "qlib_data_snapshot_sha256": ("research-sha"),
                "strict_eval_data_snapshot_sha256": ("strict-sha"),
                "research_provider_last_trading_day": ("2020-07-31"),
                "rdagent_version": "0.8.0",
                "rdagent_commit": "commit-sha",
            },
        },
    }


def _artifact_manifest(
    path: Path,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": ("agent-alpha-audit.artifact-recovery.v1"),
                "artifact_tree_sha256": "tree-sha",
                "summary": {
                    "recovered_artifact_count": 79,
                    "final_cumulative_library_factor_count": 12,
                },
            }
        ),
        encoding="utf-8",
    )


def test_build_spec_separates_selection_and_model_validation(
    tmp_path: Path,
) -> None:
    config = tmp_path / "conf_combined_factors.yaml"
    config.write_text(
        PRIMARY_YAML,
        encoding="utf-8",
    )

    events = tmp_path / "events.jsonl"

    _write_jsonl(
        events,
        [
            _run_config(),
            {
                "trial_id": "0",
                "tag": "runtime_qlib_config",
                "payload": {
                    "config_name": ("conf_combined_factors.yaml"),
                    "config_path": str(config),
                    "config_sha256": _sha(config),
                    "status": "match",
                },
            },
        ],
    )

    artifacts = tmp_path / "artifact.json"
    _artifact_manifest(artifacts)

    out = tmp_path / "spec.json"

    spec = build_rdagent_evaluation_spec(
        logical_events=events,
        artifact_manifest=artifacts,
        out_path=out,
        runtime_versions={
            "pyqlib": "0.9.7",
            "lightgbm": "4.7.0",
            "pandas": "2.3.3",
            "numpy": "2.4.6",
        },
    )

    assert spec["periods"]["model_validation"] == {
        "start": "2015-01-01",
        "end": "2016-12-31",
        "role": ("early_stopping_and_model_validation"),
    }

    assert spec["periods"]["agent_visible_selection"]["start"] == "2017-01-01"

    assert spec["phases"]["strict_frozen_oos"]["handler_end_time_override"] == "2026-09-10"

    assert spec["portfolio"]["execution"]["signal_lag_steps"] == 1

    assert spec["combination_model"]["effective_defaults_from_pyqlib_0_9_7"]["num_boost_round"] == 1000

    assert spec["data_semantics"]["baseline_features"]["count"] == 2

    text = out.read_text()
    assert str(tmp_path) not in text
    assert "/home/" not in text


def test_build_spec_rejects_runtime_config_hash_drift(
    tmp_path: Path,
) -> None:
    config = tmp_path / "conf_combined_factors.yaml"
    config.write_text(
        PRIMARY_YAML,
        encoding="utf-8",
    )

    events = tmp_path / "events.jsonl"

    _write_jsonl(
        events,
        [
            _run_config(),
            {
                "trial_id": "0",
                "tag": "runtime_qlib_config",
                "payload": {
                    "config_name": ("conf_combined_factors.yaml"),
                    "config_path": str(config),
                    "config_sha256": _sha(config),
                    "status": "match",
                },
            },
            {
                "trial_id": "1",
                "tag": "runtime_qlib_config",
                "payload": {
                    "config_name": ("conf_combined_factors.yaml"),
                    "config_path": str(config),
                    "config_sha256": "different",
                    "status": "match",
                },
            },
        ],
    )

    artifacts = tmp_path / "artifact.json"
    _artifact_manifest(artifacts)

    with pytest.raises(
        EvaluationSpecError,
        match="hash drift",
    ):
        build_rdagent_evaluation_spec(
            logical_events=events,
            artifact_manifest=artifacts,
            out_path=tmp_path / "spec.json",
            runtime_versions={},
        )


def test_spec_does_not_claim_upstream_determinism(
    tmp_path: Path,
) -> None:
    config = tmp_path / "conf_combined_factors.yaml"
    config.write_text(
        PRIMARY_YAML,
        encoding="utf-8",
    )

    events = tmp_path / "events.jsonl"

    _write_jsonl(
        events,
        [
            _run_config(),
            {
                "trial_id": "0",
                "tag": "runtime_qlib_config",
                "payload": {
                    "config_name": ("conf_combined_factors.yaml"),
                    "config_path": str(config),
                    "config_sha256": _sha(config),
                    "status": "match",
                },
            },
        ],
    )

    artifacts = tmp_path / "artifact.json"
    _artifact_manifest(artifacts)

    spec = build_rdagent_evaluation_spec(
        logical_events=events,
        artifact_manifest=artifacts,
        out_path=tmp_path / "spec.json",
        runtime_versions={},
    )

    assert spec["phases"]["upstream_reproduction"]["deterministic_claim"] is False

    strict = spec["phases"]["strict_selection_replay"]["determinism"]

    assert strict["required_model_overrides"] == {
        "deterministic": True,
        "force_col_wise": True,
    }
