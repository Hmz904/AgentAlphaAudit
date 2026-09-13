import pytest

from agent_alpha_audit.config_audit import (
    discover_template_contracts,
    reconcile_runtime_config_with_lock,
)

LOCK = {
    'train_start':'2008-01-01','train_end':'2014-12-31',
    'validation_start':'2015-01-01','validation_end':'2016-12-31',
    'agent_visible_test_start':'2017-01-01','agent_visible_test_end':'2020-08-01',
}

YAML = '''
qlib_init:
  provider_uri: "~/.qlib/qlib_data/cn_data"
task:
  dataset:
    kwargs:
      segments:
        train: [2008-01-01, 2014-12-31]
        valid: [2015-01-01, 2016-12-31]
        test: [2017-01-01, 2020-08-01]
'''


def test_runtime_workspace_config_is_hashed_and_reconciled(tmp_path):
    p = tmp_path / 'workspace' / 'conf_combined_factors.yaml'
    p.parent.mkdir()
    p.write_text(YAML)
    snap = reconcile_runtime_config_with_lock(
        p, LOCK, expected_provider_uri='~/.qlib/qlib_data/cn_data'
    )
    assert snap['status'] == 'match'
    assert len(snap['config_sha256']) == 64
    assert snap['segment_blocks'][0][-1] == '2020-08-01'


def test_runtime_workspace_config_fails_if_executed_copy_drifted(tmp_path):
    p = tmp_path / 'workspace' / 'conf.yaml'
    p.parent.mkdir()
    p.write_text(YAML.replace('2020-08-01', '2020-12-31'))
    with pytest.raises(ValueError, match='runtime Qlib config'):
        reconcile_runtime_config_with_lock(
            p, LOCK, expected_provider_uri='~/.qlib/qlib_data/cn_data'
        )


def test_unknown_execution_template_family_fails_closed(tmp_path):
    root = tmp_path / 'experiment'
    for fam in ('factor_template', 'model_template'):
        d = root / fam
        d.mkdir(parents=True)
        (d/'conf.yaml').write_text(YAML)
    future = root / 'future_agent_template'
    future.mkdir()
    (future/'conf.yaml').write_text(YAML)
    with pytest.raises(ValueError, match='unknown RD-Agent template families'):
        discover_template_contracts(root)
