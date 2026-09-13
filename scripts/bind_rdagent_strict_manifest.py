#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_alpha_audit.strict_manifest_binding import (
    bind_strict_eval_manifest_v4,
)


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--manifest-v3",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--artifact-manifest",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--evaluation-spec",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--composition-binding",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
    )

    args = parser.parse_args()

    result = bind_strict_eval_manifest_v4(
        manifest_v3_path=args.manifest_v3,
        artifact_manifest_path=args.artifact_manifest,
        evaluation_spec_path=args.evaluation_spec,
        composition_binding_path=args.composition_binding,
        out_path=args.out,
    )

    print(
        json.dumps(
            {
                "schema": result["schema"],
                "status": result["status"],
                "manifest_sha256": result["manifest_sha256"],
                "captured_trial_count": result["captured_trial_count"],
                "strict_replay_ready_trial_count": result["strict_replay_ready_trial_count"],
                "observed_runner_snapshot_count": result["observed_runner_snapshot_count"],
                "strict_replay_ready_cumulative_count": (result["strict_replay_ready_cumulative_count"]),
                "primary_final_library_loop_k": result["primary_final_library_loop_k"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
