import pandas as pd
import pytest

from agent_alpha_audit.ledger import TrialLedger
from agent_alpha_audit.models import TrialRecord
from agent_alpha_audit.strict_eval import assemble_trial_returns, export_strict_eval_manifest


def test_manifest_contains_trials_and_cumulative_library_states(tmp_path):
    db = tmp_path / 'x.sqlite'
    led = TrialLedger(db)
    led.upsert(TrialRecord(run_id='r', trial_id='0', agent='x', factor_expressions=['f0']))
    led.upsert(TrialRecord(run_id='r', trial_id='1', agent='x', factor_expressions=['f1']))
    led.upsert(TrialRecord(run_id='r', trial_id='2', agent='x', factor_expressions=[]))
    led.close()
    manifest = tmp_path / 'manifest.json'
    m = export_strict_eval_manifest(db, 'r', manifest)
    assert m['raw_trials_lower_bound'] == 3
    assert len(m['trial_items']) == 3
    assert len(m['cumulative_library_items']) == 3
    assert m['cumulative_library_items'][1]['factor_expressions']==['f0','f1']
    assert m['primary_final_library']['factor_expressions']==['f0','f1']

    root = tmp_path / 'eval'
    for tid in ('0','1'):
        d = root / f'trial_{tid}'; d.mkdir(parents=True)
        pd.DataFrame({'date':['2023-01-01','2023-01-02'], 'return':[0.01,-0.01]}).to_csv(d/'validation_returns.csv', index=False)
    out = tmp_path / 'returns.csv'
    c = assemble_trial_returns(manifest, root, out)
    assert c['trials_with_aligned_returns'] == 2
    assert c['coverage'] == 2/3
    assert c['date_alignment_policy']=='strict_identical'


def test_assembler_rejects_different_validation_windows(tmp_path):
    db=tmp_path/'x.sqlite'; led=TrialLedger(db)
    for i in range(2): led.upsert(TrialRecord(run_id='r',trial_id=str(i),agent='x',factor_expressions=[f'f{i}']))
    led.close(); manifest=tmp_path/'m.json'; export_strict_eval_manifest(db,'r',manifest)
    root=tmp_path/'eval'
    d=root/'trial_0'; d.mkdir(parents=True); pd.DataFrame({'date':['2023-01-01','2023-01-02'],'return':[0,1]}).to_csv(d/'validation_returns.csv',index=False)
    d=root/'trial_1'; d.mkdir(parents=True); pd.DataFrame({'date':['2023-01-02','2023-01-03'],'return':[0,1]}).to_csv(d/'validation_returns.csv',index=False)
    with pytest.raises(ValueError): assemble_trial_returns(manifest,root,tmp_path/'out.csv')


def test_external_evaluator_uses_shell_false_and_timeout(tmp_path):
    import json
    import sys

    from agent_alpha_audit.strict_eval import run_external_evaluator
    manifest=tmp_path/'m.json'
    manifest.write_text(json.dumps({
        'trial_items':[{'trial_id':'0','evaluation_unit':'trial_experiment','evaluable':True}],
        'cumulative_library_items':[]
    }))
    script=tmp_path/'writer.py'
    script.write_text('import pathlib,sys; pathlib.Path(sys.argv[2]).joinpath("result.json").write_text("{}")')
    out=tmp_path/'eval'
    r=run_external_evaluator(manifest,out,f'{sys.executable} {script} {{request}} {{outdir}}',timeout_seconds=10)
    assert r['results'][0]['status']=='ok'


def test_manifest_prefers_runtime_successful_cumulative_state(tmp_path):
    import json
    db=tmp_path/'x.sqlite'; led=TrialLedger(db)
    led.upsert(TrialRecord(
        run_id='r', trial_id='0', agent='x', factor_expressions=['proposed_bad','proposed_good'],
        artifacts={'cumulative_factor_expressions': json.dumps(['implemented_good'])}
    ))
    led.close(); mpath=tmp_path/'m.json'
    m=export_strict_eval_manifest(db,'r',mpath)
    item=m['cumulative_library_items'][0]
    assert item['factor_expressions']==['implemented_good']
    assert item['cumulative_state_source']=='runner_successful_factor_state'
