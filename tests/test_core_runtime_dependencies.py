from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_core_runtime_io_dependencies_are_direct():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    dependencies = [dep.lower() for dep in project["project"]["dependencies"]]

    for package in ("tables", "pyarrow"):
        assert any(dep.startswith(package) for dep in dependencies), (
            f"{package} must be a direct core dependency because the evaluator uses its pandas IO backend"
        )
