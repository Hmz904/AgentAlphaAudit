from agent_alpha_audit.audit.waterfall import plot_audit_waterfall


def test_waterfall_writes_svg(tmp_path):
    out = tmp_path / 'x.svg'
    plot_audit_waterfall({'agent_reported':2.0,'pit':1.5,'frozen_oos':0.8}, out)
    assert out.exists() and out.stat().st_size > 100
