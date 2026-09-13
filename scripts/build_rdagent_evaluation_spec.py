#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_alpha_audit.evaluation_spec import (
    build_rdagent_evaluation_spec,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--logical-events",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--artifact-manifest",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
    )
    args = parser.parse_args()

    spec = build_rdagent_evaluation_spec(
        logical_events=args.logical_events,
        artifact_manifest=args.artifact_manifest,
        out_path=args.out,
    )

    print(
        json.dumps(
            {
                "schema": spec["schema"],
                "status": spec["status"],
                "spec_sha256": spec["spec_sha256"],
                "runtime_config": (spec["evidence"]["runtime_primary_config"]),
                "artifact_tree_sha256": (spec["evidence"]["artifact_recovery"]["artifact_tree_sha256"]),
                "selection_period": (spec["periods"]["agent_visible_selection"]),
                "frozen_oos": (spec["periods"]["frozen_oos"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
