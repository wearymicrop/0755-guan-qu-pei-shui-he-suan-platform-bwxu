import copy

from app.modules.m8_sources import rules as m8


def test_restricted_contact_guard_blocks_outlet(dual_data, monkeypatch):
    """护栏：若裁决被绕过、再生水实际进入受限段，硬护栏阻断斗口并留证。"""
    data = copy.deepcopy(dual_data)
    data["sources"] = [{"source": "X", "kind": "reclaimed", "channel": "西支渠",
                        "offered": "0.5", "unit": "m³"}]

    def force_admit(_data, _reachable, _subtree):
        return [{"source": "X", "kind": m8.RECLAIMED, "channel": "西支渠", "offered_l": 500,
                 "admitted_l": 500, "plan": m8.PLAN_A, "state": "admitted",
                 "evidence": {"table": "sources", "line": 1, "raw": {}}}], []

    monkeypatch.setattr(m8, "read_sources", force_admit)
    previous = _pre_stages(data)
    out = m8.run(data, previous)
    codes = [i["code"] for i in out["issues"]]
    assert "RESTRICTED_CONTACT" in codes
    assert any(row["outlet"] == "302" for row in out["blocked_outlets"])
    west = next(s for s in out["sections"] if s["channel"] == "西支渠")
    assert west["mix_blocked"] is True


def _pre_stages(data):
    from app.pipeline import calculate
    full = calculate(data)
    return {"batches": full["batches"], "rights": full["rights"], "channels": full["channels"]}
