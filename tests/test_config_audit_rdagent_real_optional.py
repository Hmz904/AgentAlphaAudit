import importlib.util
from pathlib import Path

import pytest

from agent_alpha_audit.config_audit import discover_template_contracts


def test_installed_rdagent_templates_have_explicit_segments_and_single_provider():
    try:
        spec=importlib.util.find_spec('rdagent.scenarios.qlib.experiment.quant_experiment')
    except ModuleNotFoundError:
        pytest.skip('rdagent optional dependency not installed')
    if spec is None or spec.origin is None:
        pytest.skip('rdagent optional dependency not installed')
    root=Path(spec.origin).resolve().parent
    contracts=discover_template_contracts(root)
    assert contracts
    providers={c.provider_uri for c in contracts if c.provider_uri}
    assert len(providers)==1
    assert any(c.family=='factor_template' for c in contracts)
    assert any(c.family=='model_template' for c in contracts)
    for c in contracts:
        assert c.segment_blocks
        assert len(set(c.segment_blocks))==1


def test_real_rdagent_workspace_copy_contains_auditable_executed_config():
    try:
        import rdagent.scenarios.qlib.experiment.quant_experiment as qexp
        from rdagent.scenarios.qlib.experiment.workspace import QlibFBWorkspace
    except (ImportError, ModuleNotFoundError):
        pytest.skip('rdagent optional dependency not installed')
    from agent_alpha_audit.config_audit import inspect_runtime_config

    template = Path(qexp.__file__).resolve().parent / 'factor_template'
    ws = QlibFBWorkspace(template_folder_path=template)
    cfg = ws.workspace_path / 'conf_combined_factors.yaml'
    assert cfg.exists(), 'real RD-Agent workspace did not receive factor template config'
    snap = inspect_runtime_config(cfg)
    assert snap['config_sha256']
    assert len(snap['segment_blocks']) == 1
    assert snap['provider_uri']
