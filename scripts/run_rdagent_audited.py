#!/usr/bin/env python3
"""Run RD-Agent with AgentAlphaAudit sidecar capture.

v0.5 uses installed template YAMLs only as preflight and hard-gates the exact
workspace config observed immediately before each qrun; it never treats QUANT_PROP_SETTING
as execution-date evidence. The first confirmatory target is the factor-mining path;
`quant` remains available for pilot integration work but is not the v1 locked case.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import os
import platform
from pathlib import Path

import pandas as pd

from agent_alpha_audit.config_audit import reconcile_templates_with_lock, resolve_provider_uri
from agent_alpha_audit.runlock import validate_run_lock
from agent_alpha_audit.utils import safe_jsonable, sha256_file


def _runtime(experiment_kind: str):
    if experiment_kind == "factor":
        from rdagent.app.qlib_rd_loop.conf import FACTOR_PROP_SETTING
        from rdagent.app.qlib_rd_loop.factor import FactorRDLoop
        return FACTOR_PROP_SETTING, FactorRDLoop
    from rdagent.app.qlib_rd_loop.conf import QUANT_PROP_SETTING
    from rdagent.app.qlib_rd_loop.quant import QuantRDLoop
    return QUANT_PROP_SETTING, QuantRDLoop


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default="audit_events.jsonl")
    ap.add_argument("--loop-n", type=int, default=2)
    ap.add_argument("--all-duration", default=None)
    ap.add_argument("--rdagent-ref", default="UNRECORDED", help="Exact git commit/tag for provenance")
    ap.add_argument("--run-kind", choices=["pilot", "confirmatory"], default="pilot")
    ap.add_argument("--run-lock", help="Required LOCKED JSON for confirmatory runs")
    ap.add_argument("--scenario", choices=["factor", "quant"], default="factor")
    ap.add_argument(
        "--qlib-calendar",
        help="Optional diagnostic override. If supplied it MUST resolve to <template provider_uri>/calendars/day.txt.",
    )
    args = ap.parse_args()

    lock = None
    if args.run_kind == "confirmatory":
        if not args.run_lock:
            ap.error("--run-lock is required for confirmatory runs")
        lock = validate_run_lock(args.run_lock)
        if lock.get("audit_scenario") != args.scenario:
            raise SystemExit(f"locked audit_scenario={lock.get('audit_scenario')!r} but CLI scenario={args.scenario!r}")
        args.loop_n = int(lock["confirmatory_loop_budget"])
        if args.rdagent_ref == "UNRECORDED":
            args.rdagent_ref = str(lock["rdagent_commit"])
    else:
        if args.loop_n > 2:
            raise SystemExit("pilot runs are capped at 2 loops; use confirmatory mode only after a LOCKED run file exists")
        # A filled DRAFT lock may be supplied during the pilot specifically to dry-run
        # the exact confirmatory template/provider/physical-holdout gate.
        if args.run_lock:
            lock = validate_run_lock(args.run_lock, require_locked=False)
            if lock.get("audit_scenario") != args.scenario:
                raise SystemExit(f"draft audit_scenario={lock.get('audit_scenario')!r} but CLI scenario={args.scenario!r}")

    import rdagent.scenarios.qlib.experiment.quant_experiment as qexp
    from rdagent.core.conf import RD_AGENT_SETTINGS

    prop_setting, loop_cls = _runtime(args.scenario)
    RD_AGENT_SETTINGS.step_semaphore = 1
    RD_AGENT_SETTINGS.subproc_step = False

    from agent_alpha_audit.integrations.rdagent_probe import EventSink, install_rdagent_probe

    template_reconciliation = None
    data_cutoff_evidence = None
    experiment_dir = Path(qexp.__file__).resolve().parent
    if lock is not None:
        template_reconciliation = reconcile_templates_with_lock(experiment_dir, lock)
        provider_root = resolve_provider_uri(template_reconciliation["provider_uri"])
        expected_calendar = (provider_root / "calendars" / "day.txt").resolve()
        if args.qlib_calendar and Path(args.qlib_calendar).expanduser().resolve() != expected_calendar:
            raise SystemExit(
                f"--qlib-calendar must be the calendar under the provider_uri used by installed templates: {expected_calendar}"
            )
        cal = expected_calendar
        if not cal.exists():
            raise SystemExit(f"derived Qlib calendar does not exist: {cal}")
        try:
            cal.relative_to(provider_root)
        except ValueError as exc:
            raise SystemExit("derived calendar is not under the runtime template provider_uri") from exc
        dates = pd.to_datetime(pd.read_csv(cal, header=None).iloc[:, 0], errors="coerce").dropna()
        if dates.empty:
            raise SystemExit("Qlib calendar contained no parseable dates")
        max_date = dates.max().date().isoformat()
        frozen_start = pd.Timestamp(lock["frozen_oos_start"]).date().isoformat()
        if max_date >= frozen_start:
            raise SystemExit(
                f"physical holdout violation: runtime provider calendar max date {max_date} is not before frozen OOS start {frozen_start}"
            )
        data_cutoff_evidence = {
            "provider_uri_from_runtime_templates": str(provider_root),
            "calendar_path": str(cal),
            "calendar_sha256": sha256_file(cal),
            "max_available_date": max_date,
            "frozen_oos_start": frozen_start,
            "status": "physically_excluded",
        }

    install_rdagent_probe(
        args.events,
        loop_cls=loop_cls,
        run_lock=lock,
        expected_provider_uri=(template_reconciliation or {}).get("provider_uri"),
    )

    try:
        pkg_version = importlib.metadata.version("rdagent")
    except importlib.metadata.PackageNotFoundError:
        pkg_version = "unknown"

    EventSink(args.events).emit(
        "run_config",
        {
            "rdagent_ref": args.rdagent_ref,
            "rdagent_package_version": pkg_version,
            "python": platform.python_version(),
            "chat_model": os.environ.get("CHAT_MODEL"),
            "embedding_model": os.environ.get("EMBEDDING_MODEL"),
            "step_semaphore": RD_AGENT_SETTINGS.step_semaphore,
            "subproc_step": RD_AGENT_SETTINGS.subproc_step,
            "max_parallel": RD_AGENT_SETTINGS.get_max_parallel(),
            "scenario": args.scenario,
            "prop_setting": safe_jsonable(prop_setting),
            "loop_n": args.loop_n,
            "run_kind": args.run_kind,
            "run_lock": safe_jsonable(lock) if lock is not None else None,
            "template_reconciliation": template_reconciliation,
            "physical_data_cutoff": data_cutoff_evidence,
        },
        "__run__",
    )

    loop = loop_cls(prop_setting)
    asyncio.run(loop.run(loop_n=args.loop_n, all_duration=args.all_duration))


if __name__ == "__main__":
    main()
