import copy

from app.pipeline import calculate


def test_dual_sample_matched(dual):
    assert dual["balance"]["status"] == "MATCHED"
    assert dual["balance"]["difference_l"] == 0
    assert dual["dispatch"]["state"] == "ready"


def test_plan_b_withholds_shared_main_canal(dual):
    decisions = {d["source"]: d for d in dual["sources"]["decisions"]}
    r1 = decisions["R1再生水厂"]
    assert r1["plan"] == "B_PROTECT" and r1["state"] == "withheld"
    assert r1["admitted_l"] == 0 and r1["offered_l"] == 5000


def test_plan_a_admits_clean_subtree(dual):
    decisions = {d["source"]: d for d in dual["sources"]["decisions"]}
    r2 = decisions["R2再生水厂"]
    assert r2["plan"] == "A_REPLENISH" and r2["state"] == "admitted"
    assert r2["admitted_l"] == 2000


def test_subtree_restricted_flags(dual):
    flags = {s["channel"]: s["subtree_restricted"] for s in dual["sources"]["sections"]}
    assert flags == {"总干渠": True, "西支渠": True, "苗圃渠": True, "东支渠": False, "北斗渠": False}


def test_restricted_outlets_never_receive_reclaimed(dual):
    for outlet in ("302", "501"):
        row = next(a for a in dual["tail"]["allocations"] if a["outlet"] == outlet)
        assert row["reclaimed_l"] == 0 and row["fresh_l"] == row["allocated_l"]


def test_outlet_split_conservation(dual):
    for row in dual["tail"]["allocations"]:
        assert row["fresh_l"] + row["reclaimed_l"] == row["allocated_l"]


def test_section_identity(dual):
    for ledger in dual["balance"]["ledgers"]:
        inflow = (ledger["inflow_fresh_l"] + ledger["inflow_reclaimed_l"]
                  + ledger["injected_fresh_l"] + ledger["injected_reclaimed_l"])
        outflow = (ledger["loss_fresh_l"] + ledger["loss_reclaimed_l"]
                   + ledger["child_fresh_l"] + ledger["child_reclaimed_l"]
                   + ledger["allocated_fresh_l"] + ledger["allocated_reclaimed_l"]
                   + ledger["remainder_fresh_l"] + ledger["remainder_reclaimed_l"] + ledger["held_l"])
        assert inflow == outflow


def test_parent_child_transfer_conservation(dual):
    sections = {s["channel"]: s for s in dual["sources"]["sections"]}
    sums = {}
    for section in dual["sources"]["sections"]:
        if section["parent"] is not None:
            agg = sums.setdefault(section["parent"], [0, 0])
            agg[0] += section["inflow_fresh_l"]
            agg[1] += section["inflow_reclaimed_l"]
    for parent, (fresh, reclaimed) in sums.items():
        assert (fresh, reclaimed) == (sections[parent]["draw_fresh_l"], sections[parent]["draw_reclaimed_l"])


def test_global_identity(dual):
    totals = dual["balance"]["totals"]
    assert (totals["fresh_supply_l"] + totals["fresh_injected_l"] + totals["reclaimed_admitted_l"]
            == totals["loss_fresh_l"] + totals["loss_reclaimed_l"]
            + totals["allocated_fresh_l"] + totals["allocated_reclaimed_l"]
            + totals["remaining_fresh_l"] + totals["remaining_reclaimed_l"])


def test_unused_margins(dual):
    totals = dual["balance"]["totals"]
    assert totals["reclaimed_withheld_l"] == 5000  # R1 未启用余量留账
    assert totals["remaining_reclaimed_l"] == 75
    assert totals["fresh_saved_l"] == totals["allocated_reclaimed_l"] == 1825


def test_withheld_injection_keeps_restricted_supply(dual_data):
    # 方案B 缓注后受限斗口仍按本轮权证受水，未错过供水。
    result = calculate(dual_data)
    served = {a["outlet"]: a["allocated_l"] for a in result["dispatch"]["receipts"]}
    assert served["302"] == 1400 and served["501"] == 1200


def test_injection_into_restricted_channel_withheld(dual_data):
    data = copy.deepcopy(dual_data)
    data["sources"] = [{"source": "X", "kind": "reclaimed", "channel": "西支渠", "offered": "1", "unit": "m³"}]
    result = calculate(data)
    assert result["sources"]["decisions"][0]["state"] == "withheld"
    assert all(a["reclaimed_l"] == 0 for a in result["tail"]["allocations"] if a["channel"] == "西支渠")


def test_unreachable_injection_route_blocked(dual_data):
    data = copy.deepcopy(dual_data)
    data["sources"] = [{"source": "Q", "kind": "reclaimed", "channel": "幽灵渠", "offered": "1", "unit": "m³"}]
    result = calculate(data)
    assert "SOURCE_ROUTE_BLOCKED" in [i["code"] for i in result["balance"]["issues"]]


def test_bad_source_row_isolated(dual_data):
    data = copy.deepcopy(dual_data)
    data["sources"].append({"source": "坏", "kind": "seawater", "channel": "总干渠", "offered": "1", "unit": "m³"})
    result = calculate(data)
    assert "BAD_SOURCE" in [i["code"] for i in result["balance"]["issues"]]


def test_unknown_restriction_flagged(dual_data):
    data = copy.deepcopy(dual_data)
    data["restrictions"] = [{"outlet": "999", "purpose": "饮水池"}]
    result = calculate(data)
    assert "UNKNOWN_RESTRICTION" in [i["code"] for i in result["balance"]["issues"]]


def test_head_mismatch_on_root_injection(dual_data):
    data = copy.deepcopy(dual_data)
    data["sources"] = [{"source": "Z", "kind": "fresh", "channel": "总干渠", "offered": "1", "unit": "m³"}]
    result = calculate(data)
    assert "SOURCE_HEAD_MISMATCH" in [i["code"] for i in result["balance"]["issues"]]


def test_receipt_provenance_includes_source(dual):
    east = next(r for r in dual["dispatch"]["receipts"] if r["channel"] == "东支渠")
    tables = [s["table"] for s in east["sources"]]
    assert "sources" in tables and "rights" in tables and "channels" in tables


def test_legacy_samples_have_no_reclaimed(clean, dirty):
    for result in (clean, dirty):
        assert result["balance"]["totals"]["reclaimed_admitted_l"] == 0
        assert all(r["reclaimed_l"] == 0 for r in result["tail"]["allocations"])
