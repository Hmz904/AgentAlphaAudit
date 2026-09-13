from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from agent_alpha_audit.rdagent_evaluator import (
    combine_factor_frames,
    prepare_strict_evaluation,
    sha256_file,
)


def _write_json(
    path: Path,
    value: dict,
) -> None:
    path.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _template(path: Path) -> None:
    value = {
        "qlib_init": {
            "provider_uri": "old",
            "region": "cn",
        },
        "data_handler_config": {
            "start_time": "2008-01-01",
            "end_time": "2022-08-01",
            "instruments": "csi300",
            "data_loader": {
                "class": "NestedDataLoader",
                "kwargs": {
                    "dataloader_l": [
                        {
                            "class": ("qlib.data.dataset.loader.StaticDataLoader"),
                            "kwargs": {
                                "config": "old.parquet",
                            },
                        }
                    ]
                },
            },
        },
        "port_analysis_config": {
            "strategy": {
                "class": "TopkDropoutStrategy",
            },
            "backtest": {
                "start_time": "2017-01-01",
                "end_time": "2020-08-01",
                "exchange_kwargs": {
                    "open_cost": 0.0005,
                    "close_cost": 0.0015,
                },
            },
        },
        "task": {
            "model": {
                "class": "LGBModel",
                "kwargs": {
                    "loss": "mse",
                },
            },
            "dataset": {
                "kwargs": {
                    "segments": {
                        "train": [
                            "x",
                            "x",
                        ],
                        "valid": [
                            "x",
                            "x",
                        ],
                        "test": [
                            "x",
                            "x",
                        ],
                    }
                }
            },
            "record": [
                {
                    "class": "PortAnaRecord",
                    "kwargs": {
                        "config": {},
                    },
                }
            ],
        },
    }

    path.write_text(
        yaml.safe_dump(
            value,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _spec(path: Path) -> dict:
    value = {
        "schema": ("agent-alpha-audit.rdagent-evaluation-spec.v1"),
        "spec_sha256": "semantic-test",
        "periods": {
            "train": {
                "start": "2008-01-01",
                "end": "2014-12-31",
            },
            "model_validation": {
                "start": "2015-01-01",
                "end": "2016-12-31",
            },
            "agent_visible_selection": {
                "start": "2017-01-01",
                "end": "2020-08-01",
            },
            "frozen_oos": {
                "start": "2020-08-03",
                "end": "2026-09-10",
            },
        },
        "phases": {
            "strict_selection_replay": {
                "provider": "research",
                "train_period": "train",
                "validation_period": ("model_validation"),
                "test_period": ("agent_visible_selection"),
                "costs": {
                    "open_cost": 0.001,
                    "close_cost": 0.001,
                },
                "determinism": {
                    "required_model_overrides": {
                        "deterministic": True,
                        "force_col_wise": True,
                    }
                },
            },
            "strict_frozen_oos": {
                "provider": ("strict_full_history"),
                "train_period": "train",
                "validation_period": ("model_validation"),
                "test_period": "frozen_oos",
                "handler_end_time_override": ("2026-09-10"),
                "costs": {
                    "open_cost": 0.001,
                    "close_cost": 0.001,
                },
                "determinism": {
                    "required_model_overrides": {
                        "deterministic": True,
                        "force_col_wise": True,
                    }
                },
            },
        },
    }

    _write_json(
        path,
        value,
    )

    return value


def test_combine_matches_rdagent_semantics():
    idx = pd.MultiIndex.from_tuples(
        [
            (
                pd.Timestamp("2020-01-01"),
                "A",
            ),
            (
                pd.Timestamp("2020-01-02"),
                "A",
            ),
        ],
        names=[
            "datetime",
            "instrument",
        ],
    )

    a = pd.DataFrame(
        {
            "A": [
                1.0,
                2.0,
            ]
        },
        index=idx,
    )

    b = pd.DataFrame(
        {
            "B": [
                3.0,
                float("nan"),
            ]
        },
        index=idx,
    )

    out = combine_factor_frames([a, b])

    assert len(out) == 1
    assert list(out.columns.get_level_values(0)) == [
        "feature",
        "feature",
    ]
    assert list(out.columns.get_level_values(1)) == [
        "A",
        "B",
    ]


def test_prepare_executes_bound_factor(
    tmp_path: Path,
):
    artifact_root = tmp_path / "artifacts"
    rel = Path("trials/trial_00/slot_00__TestFactor/factor.py")
    source = artifact_root / rel
    source.parent.mkdir(parents=True)

    source.write_text(
        """import pandas as pd
df = pd.read_hdf("daily_pv.h5", key="data")
x = df[["$close"]].copy()
x.columns = ["TestFactor"]
x.to_hdf("result.h5", key="data", mode="w")
""",
        encoding="utf-8",
    )

    idx = pd.MultiIndex.from_tuples(
        [
            (
                pd.Timestamp("2020-01-01"),
                "A",
            ),
            (
                pd.Timestamp("2020-01-02"),
                "A",
            ),
        ],
        names=[
            "datetime",
            "instrument",
        ],
    )

    daily = tmp_path / "daily_pv.h5"

    pd.DataFrame(
        {
            "$close": [
                1.0,
                2.0,
            ]
        },
        index=idx,
    ).to_hdf(
        daily,
        key="data",
        mode="w",
    )

    spec_path = tmp_path / "spec.json"
    spec = _spec(spec_path)

    template = tmp_path / "template.yaml"
    _template(template)

    request = {
        "evaluation_unit": ("cumulative_factor_library_at_loop_k"),
        "strict_replay_ready": True,
        "evaluable": True,
        "composition_binding": {
            "verified": True,
        },
        "evaluation_spec": {
            "verified": True,
            "file_sha256": (sha256_file(spec_path)),
            "spec_sha256": spec["spec_sha256"],
        },
        "implementation_artifact": {
            "artifact_count": 1,
            "artifact_hashes_verified": True,
            "composition_sha256": "abc",
            "artifacts": [
                {
                    "name": "TestFactor",
                    "relative_path": str(rel),
                    "sha256": sha256_file(source),
                    "slot_index": 0,
                    "source_trial_id": 0,
                }
            ],
        },
        "loop_k": "0",
    }

    request_path = tmp_path / "request.json"
    _write_json(
        request_path,
        request,
    )

    provider = tmp_path / "provider"
    provider.mkdir()

    out = tmp_path / "out"

    result = prepare_strict_evaluation(
        request_path=request_path,
        out_dir=out,
        artifact_root=artifact_root,
        evaluation_spec_path=(spec_path),
        template_config_path=template,
        provider_path=provider,
        daily_pv_path=daily,
        phase_name=("strict_selection_replay"),
        expected_template_sha256=(sha256_file(template)),
        expected_daily_pv_sha256=(sha256_file(daily)),
        execute_factors=True,
        factor_timeout_seconds=30,
    )

    assert result["status"] == "factor_outputs_ready"
    assert result["combined_factor_columns"] == ["TestFactor"]

    parquet = pd.read_parquet(out / "combined_factors_df.parquet")

    assert list(parquet.columns.get_level_values(0)) == ["feature"]

    cfg = yaml.safe_load((out / "conf_strict.yaml").read_text(encoding="utf-8"))

    kwargs = cfg["task"]["model"]["kwargs"]

    assert kwargs["deterministic"] is True
    assert kwargs["force_col_wise"] is True
    assert cfg["port_analysis_config"]["backtest"]["exchange_kwargs"]["open_cost"] == 0.001


def test_build_config_counts_yaml_alias_once(tmp_path: Path):
    from agent_alpha_audit.rdagent_evaluator import build_strict_config

    spec_path = tmp_path / "spec.json"
    _spec(spec_path)

    template = tmp_path / "template.yaml"
    template.write_text(
        """
qlib_init:
  provider_uri: old
  region: cn

data_handler_config: &data_handler_config
  start_time: 2008-01-01
  end_time: 2022-08-01
  instruments: csi300
  data_loader:
    class: NestedDataLoader
    kwargs:
      dataloader_l:
        - class: qlib.data.dataset.loader.StaticDataLoader
          kwargs:
            config: old.parquet

port_analysis_config: &port_analysis_config
  strategy:
    class: TopkDropoutStrategy
  backtest:
    start_time: 2017-01-01
    end_time: 2020-08-01
    exchange_kwargs:
      open_cost: 0.0005
      close_cost: 0.0015

task:
  model:
    class: LGBModel
    kwargs:
      loss: mse
  dataset:
    kwargs:
      handler:
        class: DataHandlerLP
        kwargs: *data_handler_config
      segments:
        train: [2008-01-01, 2014-12-31]
        valid: [2015-01-01, 2016-12-31]
        test: [2017-01-01, 2020-08-01]
  record:
    - class: PortAnaRecord
      kwargs:
        config: *port_analysis_config
""".lstrip(),
        encoding="utf-8",
    )

    provider = tmp_path / "provider"
    provider.mkdir()

    cfg = build_strict_config(
        template,
        spec_path,
        provider,
        "strict_selection_replay",
    )

    top_loader = cfg["data_handler_config"]["data_loader"]["kwargs"]["dataloader_l"][0]

    aliased_loader = cfg["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["data_loader"]["kwargs"][
        "dataloader_l"
    ][0]

    assert top_loader is aliased_loader
    assert top_loader["kwargs"]["config"] == "combined_factors_df.parquet"


def test_finalize_selection_returns(tmp_path: Path):
    from agent_alpha_audit.rdagent_evaluator import (
        finalize_selection_returns,
    )

    dates = pd.DatetimeIndex(
        pd.to_datetime(
            [
                "2020-01-02",
                "2020-01-03",
                "2020-01-06",
            ]
        ),
        name="datetime",
    )

    net = pd.Series(
        [
            0.0,
            0.01,
            -0.005,
        ],
        index=dates,
    )

    cost = pd.Series(
        [
            0.0,
            0.001,
            0.001,
        ],
        index=dates,
    )

    gross = net + cost

    bench = pd.Series(
        [
            0.0,
            0.002,
            -0.001,
        ],
        index=dates,
    )

    account = pd.Series(
        [
            100.0,
            101.0,
            100.495,
        ],
        index=dates,
    )

    ret = pd.DataFrame(
        {
            "account": account,
            "return": gross,
            "cost": cost,
            "bench": bench,
        },
        index=dates,
    )

    ret_path = tmp_path / "ret.pkl"
    ret.to_pickle(ret_path)

    metrics = pd.DataFrame(
        {
            "0": {
                "1day.excess_return_without_cost.mean": float((gross - bench).mean()),
                "1day.excess_return_with_cost.mean": float((net - bench).mean()),
            }
        }
    )

    metrics_path = tmp_path / "qlib_res.csv"
    metrics.to_csv(metrics_path)

    calendar_path = tmp_path / "selection_calendar.csv"

    pd.DataFrame({"date": dates.strftime("%Y-%m-%d")}).to_csv(
        calendar_path,
        index=False,
    )

    out_csv = tmp_path / "validation_returns.csv"
    contract_path = tmp_path / "selection_return_contract_v1.json"

    summary = finalize_selection_returns(
        ret_path=ret_path,
        qlib_metrics_path=metrics_path,
        reference_calendar_csv=(calendar_path),
        out_csv=out_csv,
        contract_json=contract_path,
    )

    observed = pd.read_csv(out_csv)

    assert summary["selection_return_rows"] == 3

    assert observed["date"].tolist() == [
        "2020-01-02",
        "2020-01-03",
        "2020-01-06",
    ]

    pd.testing.assert_series_equal(
        observed["return"],
        pd.Series(
            [
                0.0,
                0.01,
                -0.005,
            ],
            name="return",
        ),
        check_exact=False,
        rtol=0.0,
        atol=1e-15,
    )

    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    assert contract["benchmark_adjusted"] is False

    assert contract["locked_calendar_exact_match"] is True


def test_semantic_return_digest_ignores_machine_precision_noise():
    from agent_alpha_audit.rdagent_evaluator import (
        selection_returns_semantic_sha256,
    )

    dates = pd.DatetimeIndex(
        pd.to_datetime(
            [
                "2020-01-02",
                "2020-01-03",
                "2020-01-06",
            ]
        )
    )

    a = [
        0.0,
        0.01,
        -0.005,
    ]

    b = [
        0.0,
        0.01 + 3e-16,
        -0.005 - 4e-16,
    ]

    assert a != b

    assert selection_returns_semantic_sha256(
        dates,
        a,
    ) == selection_returns_semantic_sha256(
        dates,
        b,
    )
