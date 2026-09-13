from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .utils import sha256_file

_SEG_RE = re.compile(r"^\s*(train|valid|test)\s*:\s*\[\s*([^,\]]+)\s*,\s*([^\]]+)\s*\]\s*$")
_PROVIDER_RE = re.compile(r"^\s*provider_uri\s*:\s*[\"']?([^\"'#]+?)[\"']?\s*(?:#.*)?$")


@dataclass(frozen=True)
class TemplateContract:
    path: str
    family: str
    provider_uri: str | None
    segment_blocks: tuple[tuple[str, str, str, str, str, str], ...]


def _clean_scalar(x: str) -> str:
    return x.strip().strip("'\"")


def _segment_blocks(text: str) -> list[dict[str, list[str]]]:
    """Parse literal Qlib `segments:` blocks without trying to render Jinja YAML.

    RD-Agent v0.8.0 templates contain Jinja expressions that are not valid raw YAML,
    so a text parser is safer for this hard gate. Every literal train/valid/test block
    is collected; callers must reject ambiguity rather than taking a first match.
    """
    lines = text.splitlines()
    blocks: list[dict[str, list[str]]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not re.match(r"^\s*segments\s*:\s*$", line):
            i += 1
            continue
        indent = len(line) - len(line.lstrip())
        block: dict[str, list[str]] = {}
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                break
            m = _SEG_RE.match(nxt)
            if m:
                block[m.group(1)] = [_clean_scalar(m.group(2)), _clean_scalar(m.group(3))]
            j += 1
        if {"train", "valid", "test"}.issubset(block):
            blocks.append(block)
        i = max(j, i + 1)
    return blocks


def _provider_uris(text: str) -> list[str]:
    vals: list[str] = []
    for line in text.splitlines():
        m = _PROVIDER_RE.match(line)
        if m:
            vals.append(_clean_scalar(m.group(1)))
    return vals


def inspect_template_file(path: str | Path, family: str) -> TemplateContract:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    providers = sorted(set(_provider_uris(text)))
    if len(providers) > 1:
        raise ValueError(f"template {p} contains multiple provider_uri values: {providers}")
    blocks = _segment_blocks(text)
    tuples = []
    for b in blocks:
        tuples.append((b["train"][0], b["train"][1], b["valid"][0], b["valid"][1], b["test"][0], b["test"][1]))
    return TemplateContract(
        path=str(p.resolve()),
        family=family,
        provider_uri=providers[0] if providers else None,
        segment_blocks=tuple(tuples),
    )


KNOWN_EXECUTION_TEMPLATE_FAMILIES = {"factor_template", "model_template"}


def discover_template_contracts(experiment_dir: str | Path) -> list[TemplateContract]:
    """Inspect every YAML family under the installed RD-Agent Qlib experiment tree.

    Fail closed: if a previously unknown template family contains an executable
    train/valid/test segment block, the audit refuses to proceed until that family is
    explicitly reviewed and added to ``KNOWN_EXECUTION_TEMPLATE_FAMILIES``.
    """
    root = Path(experiment_dir).resolve()
    contracts: list[TemplateContract] = []
    unknown_execution_families: list[dict[str, str]] = []
    for folder in sorted(x for x in root.iterdir() if x.is_dir()):
        family = folder.name
        for path in sorted(folder.rglob("*.yaml")):
            c = inspect_template_file(path, family)
            if not c.segment_blocks:
                continue
            if family not in KNOWN_EXECUTION_TEMPLATE_FAMILIES:
                unknown_execution_families.append({"family": family, "template": c.path})
            contracts.append(c)
    if unknown_execution_families:
        raise ValueError(
            "unknown RD-Agent template families contain executable Qlib segments; "
            f"audit contract must be reviewed before proceeding: {unknown_execution_families}"
        )
    if not contracts:
        raise ValueError(f"no Qlib execution template with train/valid/test segments found under {root}")
    return contracts


def reconcile_templates_with_lock(experiment_dir: str | Path, lock: dict[str, Any]) -> dict[str, Any]:
    """Hard-gate the installed RD-Agent Qlib templates against the run lock.

    Every literal segment block across factor/model templates must equal the locked
    dates. No recursive 'first matching key' behavior is allowed.
    """
    expected = (
        str(lock["train_start"]), str(lock["train_end"]),
        str(lock["validation_start"]), str(lock["validation_end"]),
        str(lock["agent_visible_test_start"]), str(lock["agent_visible_test_end"]),
    )
    contracts = discover_template_contracts(experiment_dir)
    mismatches: list[dict[str, Any]] = []
    providers: set[str] = set()
    serialized: list[dict[str, Any]] = []
    for c in contracts:
        if c.provider_uri:
            providers.add(c.provider_uri)
        if len(set(c.segment_blocks)) != 1:
            mismatches.append({"template": c.path, "reason": "ambiguous_segment_blocks", "blocks": c.segment_blocks})
        for block in c.segment_blocks:
            if block != expected:
                mismatches.append({"template": c.path, "reason": "segment_mismatch", "actual": block, "locked": expected})
        serialized.append(asdict(c))
    if len(providers) != 1:
        mismatches.append({"reason": "provider_uri_not_unique", "provider_uris": sorted(providers)})
    if mismatches:
        raise ValueError(f"installed RD-Agent Qlib templates do not match run lock: {mismatches}")
    provider = next(iter(providers))
    return {
        "status": "match",
        "source": "installed_rdagent_qlib_template_yamls",
        "experiment_dir": str(Path(experiment_dir).resolve()),
        "provider_uri": provider,
        "locked_segments": {
            "train": [expected[0], expected[1]],
            "valid": [expected[2], expected[3]],
            "test": [expected[4], expected[5]],
        },
        "templates": serialized,
    }


def resolve_provider_uri(provider_uri: str) -> Path:
    p = Path(provider_uri).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    return p.resolve()


def inspect_runtime_config(path: str | Path) -> dict[str, Any]:
    """Inspect the exact Qlib YAML file present in an experiment workspace.

    This is observation evidence, not a claim about the installed template. The file
    hash is taken from the same workspace path passed to ``qrun`` by QlibFBWorkspace.
    """
    p = Path(path).resolve()
    c = inspect_template_file(p, p.parent.name)
    return {
        "config_path": str(p),
        "config_name": p.name,
        "config_sha256": sha256_file(p),
        "provider_uri": c.provider_uri,
        "segment_blocks": [list(x) for x in c.segment_blocks],
        "status": "observed",
    }


def reconcile_runtime_config_with_lock(
    path: str | Path,
    lock: dict[str, Any],
    *,
    expected_provider_uri: str | None = None,
) -> dict[str, Any]:
    """Hard-gate the exact workspace Qlib config that is about to be executed."""
    snap = inspect_runtime_config(path)
    expected = (
        str(lock["train_start"]), str(lock["train_end"]),
        str(lock["validation_start"]), str(lock["validation_end"]),
        str(lock["agent_visible_test_start"]), str(lock["agent_visible_test_end"]),
    )
    blocks = [tuple(x) for x in snap["segment_blocks"]]
    problems: list[dict[str, Any]] = []
    if len(blocks) != 1:
        problems.append({"reason": "runtime_segment_block_count", "count": len(blocks), "blocks": blocks})
    elif blocks[0] != expected:
        problems.append({"reason": "runtime_segment_mismatch", "actual": blocks[0], "locked": expected})
    if expected_provider_uri is not None and snap.get("provider_uri") != expected_provider_uri:
        problems.append({
            "reason": "runtime_provider_uri_mismatch",
            "actual": snap.get("provider_uri"),
            "expected": expected_provider_uri,
        })
    snap["locked_segments"] = {
        "train": [expected[0], expected[1]],
        "valid": [expected[2], expected[3]],
        "test": [expected[4], expected[5]],
    }
    snap["expected_provider_uri"] = expected_provider_uri
    snap["status"] = "match" if not problems else "mismatch"
    snap["problems"] = problems
    if problems:
        raise ValueError(f"runtime Qlib config does not match run lock: {problems}")
    return snap
