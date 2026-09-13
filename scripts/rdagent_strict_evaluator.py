from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from agent_alpha_audit.rdagent_evaluator import (
    prepare_strict_evaluation,
    run_strict_selection_qrun,
)


def _write_result(
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


def main() -> int:
    p = argparse.ArgumentParser()

    p.add_argument(
        "--request",
        required=True,
    )
    p.add_argument(
        "--outdir",
        required=True,
    )
    p.add_argument(
        "--artifact-root",
        required=True,
    )
    p.add_argument(
        "--evaluation-spec",
        required=True,
    )
    p.add_argument(
        "--template-config",
        required=True,
    )
    p.add_argument(
        "--provider",
        required=True,
    )
    p.add_argument(
        "--daily-pv",
        required=True,
    )
    p.add_argument(
        "--phase",
        choices=[
            "strict_selection_replay",
            "strict_frozen_oos",
        ],
        required=True,
    )
    p.add_argument(
        "--expected-template-sha256",
    )
    p.add_argument(
        "--expected-daily-pv-sha256",
    )
    p.add_argument(
        "--execute-factors",
        action="store_true",
    )
    p.add_argument(
        "--factor-timeout-seconds",
        type=int,
        default=3600,
    )
    p.add_argument(
        "--run-qrun",
        action="store_true",
    )
    p.add_argument(
        "--reference-calendar",
    )
    p.add_argument(
        "--qrun-timeout-seconds",
        type=int,
        default=7200,
    )

    args = p.parse_args()

    if args.run_qrun and not args.execute_factors:
        p.error("--run-qrun requires --execute-factors")

    if args.run_qrun and args.phase not in {
        "strict_selection_replay",
        "strict_frozen_oos",
    }:
        p.error("qrun integration supports strict_selection_replay and strict_frozen_oos only")

    if args.run_qrun and args.phase == "strict_selection_replay" and not args.reference_calendar:
        p.error("--run-qrun requires --reference-calendar for strict_selection_replay")

    out = Path(args.outdir)
    out.mkdir(
        parents=True,
        exist_ok=True,
    )

    result_path = out / "result.json"

    started = time.perf_counter()

    try:
        result = prepare_strict_evaluation(
            request_path=args.request,
            out_dir=out,
            artifact_root=(args.artifact_root),
            evaluation_spec_path=(args.evaluation_spec),
            template_config_path=(args.template_config),
            provider_path=(args.provider),
            daily_pv_path=(args.daily_pv),
            phase_name=args.phase,
            expected_template_sha256=(args.expected_template_sha256),
            expected_daily_pv_sha256=(args.expected_daily_pv_sha256),
            execute_factors=(args.execute_factors),
            factor_timeout_seconds=(args.factor_timeout_seconds),
        )

        if args.run_qrun:
            qrun_result = run_strict_selection_qrun(
                out_dir=out,
                template_config_path=(args.template_config),
                reference_calendar_csv=(args.reference_calendar),
                qrun_timeout_seconds=(args.qrun_timeout_seconds),
                phase_name=args.phase,
            )

            result.update(qrun_result)

            result["status"] = "strict_replay_completed"

            result["duration_seconds"] = round(
                time.perf_counter() - started,
                6,
            )

            _write_result(
                result_path,
                result,
            )

        print(
            json.dumps(
                result,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    except Exception as exc:  # noqa: BLE001 - CLI boundary records every evaluator failure
        existing = {}

        if result_path.is_file():
            try:
                existing = json.loads(result_path.read_text(encoding="utf-8"))
            except (
                json.JSONDecodeError,
                OSError,
            ):
                existing = {}

        failure = {
            **existing,
            "schema": (
                existing.get("schema") or ("agent-alpha-audit.rdagent-strict-evaluator-preparation.v1")
            ),
            "status": "failed",
            "failure_class": getattr(
                exc,
                "failure_class",
                exc.__class__.__name__,
            ),
            "error": str(exc),
            "strict_replay_completed": False,
            "duration_seconds": round(
                time.perf_counter() - started,
                6,
            ),
        }

        failure.setdefault(
            "qrun_completed",
            False,
        )

        _write_result(
            result_path,
            failure,
        )

        print(
            json.dumps(
                failure,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
