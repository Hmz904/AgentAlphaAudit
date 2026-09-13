#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_alpha_audit.composition_binding import (
    build_composition_binding,
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
        "--evaluation-spec",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
    )

    args = parser.parse_args()

    result = build_composition_binding(
        logical_events=args.logical_events,
        artifact_manifest=args.artifact_manifest,
        evaluation_spec=args.evaluation_spec,
        out_path=args.out,
    )

    print(
        json.dumps(
            {
                "schema": result["schema"],
                "status": result["status"],
                "binding_sha256": result["binding_sha256"],
                "summary": result["summary"],
                "artifact_tree_sha256": (result["source_evidence"]["artifact_tree_sha256"]),
                "evaluation_spec_sha256": (result["source_evidence"]["evaluation_spec_sha256"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
