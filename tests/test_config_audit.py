import pytest

from agent_alpha_audit.config_audit import discover_template_contracts, reconcile_templates_with_lock

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

def _tree(tmp_path):
    root=tmp_path/'experiment'
    for fam in ('factor_template','model_template'):
        d=root/fam; d.mkdir(parents=True)
        (d/'conf_a.yaml').write_text(YAML)
        (d/'conf_b.yaml').write_text(YAML)
    return root

def test_template_reconciliation_reads_realistic_template_tree(tmp_path):
    root=_tree(tmp_path)
    contracts=discover_template_contracts(root)
    assert len(contracts)==4
    out=reconcile_templates_with_lock(root, LOCK)
    assert out['status']=='match'
    assert out['provider_uri']=='~/.qlib/qlib_data/cn_data'
    assert len(out['templates'])==4

def test_template_reconciliation_fails_any_template_mismatch(tmp_path):
    root=_tree(tmp_path)
    p=root/'model_template'/'conf_b.yaml'
    p.write_text(YAML.replace('2020-08-01','2020-12-31'))
    with pytest.raises(ValueError):
        reconcile_templates_with_lock(root, LOCK)
