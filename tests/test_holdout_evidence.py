import json

from agent_alpha_audit.adapters.rdagent import RDAgentSidecarAdapter


def test_holdout_no_requires_actual_config_reconciliation_and_physical_cutoff(tmp_path):
    p=tmp_path/'e.jsonl'
    events=[
        {"trial_id":"__run__","tag":"run_config","payload":{
            "run_lock":{"train_start":"2018-01-01","train_end":"2020-12-31","validation_start":"2021-01-01","validation_end":"2021-12-31","agent_visible_test_start":"2022-01-01","agent_visible_test_end":"2022-12-31","frozen_oos_start":"2023-01-01","frozen_oos_end":"2024-12-31"},
            "template_reconciliation":{"status":"match"},
            "physical_data_cutoff":{"status":"physically_excluded","max_available_date":"2022-12-30"}
        }},
        {"trial_id":"0","tag":"runtime_qlib_config","payload":{"status":"match","config_sha256":"abc"},"meta":{"id_source":"active_running_context"}},
        {"trial_id":"0","tag":"proposal","payload":{"hypothesis":"x"},"meta":{"id_source":"self.loop_idx"}},
    ]
    p.write_text('\n'.join(json.dumps(x) for x in events)+'\n')
    t=RDAgentSidecarAdapter().parse(p,'r')[0]
    assert t.holdout_access=='no'
    assert 'proposal' in t.artifacts['id_sources']
