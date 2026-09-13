#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export the locked RD-Agent selection-period "
            "trading calendar from the verified research provider."
        )
    )
    parser.add_argument(
        "--evaluation-spec",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--provider",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--metadata-out",
        type=Path,
        required=True,
    )
    args = parser.parse_args()

    import pandas as pd
    import qlib
    from qlib.constant import REG_CN
    from qlib.data import D

    spec_path = args.evaluation_spec
    provider = args.provider

    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    if spec.get("schema") != ("agent-alpha-audit.rdagent-evaluation-spec.v1"):
        raise ValueError("unexpected evaluation specification schema")

    period = spec["periods"]["agent_visible_selection"]
    research = spec["provider_identity"]["research"]
    output_contract = spec["phases"]["strict_selection_replay"]["required_trial_output"]

    if output_contract["semantic_name"] != ("selection_period_returns"):
        raise ValueError("unexpected selection-return semantic name")

    if output_contract["compatibility_filename"] != ("validation_returns.csv"):
        raise ValueError("unexpected compatibility filename")

    raw_calendar = provider / "calendars" / "day.txt"

    if not raw_calendar.is_file():
        raise FileNotFoundError(f"provider calendar missing: {raw_calendar}")

    raw_sha = sha256_file(raw_calendar)
    expected_raw_sha = research["calendar_sha256"]

    if raw_sha != expected_raw_sha:
        raise ValueError("research provider calendar hash does not match evaluation specification")

    qlib.init(
        provider_uri=str(provider),
        region=REG_CN,
    )

    calendar = pd.DatetimeIndex(
        D.calendar(
            start_time=period["start"],
            end_time=period["end"],
            freq="day",
        )
    )

    if calendar.empty:
        raise ValueError("selection calendar is empty")

    if calendar.has_duplicates:
        raise ValueError("selection calendar contains duplicate dates")

    if not calendar.is_monotonic_increasing:
        raise ValueError("selection calendar is not chronological")

    locked_start = pd.Timestamp(period["start"])
    locked_end = pd.Timestamp(period["end"])

    if calendar.min() < locked_start:
        raise ValueError("calendar begins before locked selection period")

    if calendar.max() > locked_end:
        raise ValueError("calendar ends after locked selection period")

    actual_last = calendar.max().date().isoformat()

    if actual_last != research["last_trading_day"]:
        raise ValueError("selection calendar last trading day does not match evaluation specification")

    args.out.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    import pandas as pd

    pd.DataFrame(
        {
            "date": calendar.strftime("%Y-%m-%d"),
        }
    ).to_csv(
        args.out,
        index=False,
        lineterminator="\n",
    )

    csv_sha = sha256_file(args.out)

    metadata = {
        "schema": ("agent-alpha-audit.selection-calendar.v1"),
        "semantic_role": ("locked_agent_visible_selection_calendar"),
        "evaluation_spec_schema": spec["schema"],
        "evaluation_spec_file_sha256": (sha256_file(spec_path)),
        "evaluation_spec_sha256": spec["spec_sha256"],
        "provider_role": "research",
        "provider_snapshot_sha256": research["snapshot_sha256"],
        "provider_calendar_sha256": raw_sha,
        "source_calendar": "calendars/day.txt",
        "selection_period_start": period["start"],
        "selection_period_end": period["end"],
        "first_trading_day": (calendar.min().date().isoformat()),
        "last_trading_day": actual_last,
        "trading_day_count": len(calendar),
        "selection_calendar_csv_sha256": csv_sha,
    }

    args.metadata_out.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.metadata_out.write_text(
        json.dumps(
            metadata,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            metadata,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
