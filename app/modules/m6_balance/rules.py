from collections import defaultdict

from app.evidence import issue


def run(data, previous):
    data = data or {}
    batch = previous["batches"]
    channels = previous["channels"]
    source_stage = previous.get("sources")
    dual_mode = bool(data.get("sources") or data.get("restrictions"))
    issues = [warning for section in previous.values() for warning in section["issues"]]
    by_channel, by_outlet = defaultdict(int), defaultdict(list)
    fresh_by_channel, reclaimed_by_channel = defaultdict(int), defaultdict(int)
    for row in previous["tail"]["allocations"]:
        by_channel[row["channel"]] += row["allocated_l"]
        fresh_by_channel[row["channel"]] += row["fresh_l"]
        reclaimed_by_channel[row["channel"]] += row["reclaimed_l"]
        by_outlet[row["outlet"]].append(row["source"])
    for sources in by_outlet.values():
        if len(sources) > 1:
            issues.append(issue("DUPLICATE_OUTLET", *sources))

    total_allocated = previous["tail"]["allocated_l"]
    ledger_names = {row["channel"] for row in channels["channels"]}
    unknown_channels = {name for name, amount in by_channel.items() if name not in ledger_names and amount}
    ledgers, held = [], channels["held_at_head_l"]
    if dual_mode:
        sections = {s["channel"]: s for s in source_stage["sections"]}
        for row in channels["channels"]:
            name = row["channel"]
            section = sections[name]
            channel_total = by_channel.pop(name, 0)
            fresh_total = fresh_by_channel.pop(name, 0)
            reclaimed_total = reclaimed_by_channel.pop(name, 0)
            # 双源口径：本段可配 = m8 扩展后的清水/再生水可配之和。
            remainder = section["usable_l"] - channel_total
            if remainder < 0 or fresh_total > section["usable_fresh_l"] or reclaimed_total > section["usable_reclaimed_l"]:
                issues.append(issue("CHANNEL_UNBALANCED", row["source"]))
            ledgers.append({
                **row,
                "allocated_l": channel_total,
                "remainder_l": remainder + row["held_l"],
                "inflow_fresh_l": section["inflow_fresh_l"], "inflow_reclaimed_l": section["inflow_reclaimed_l"],
                "injected_fresh_l": section["injected_fresh_l"], "injected_reclaimed_l": section["injected_reclaimed_l"],
                "loss_fresh_l": section["loss_fresh_l"], "loss_reclaimed_l": section["loss_reclaimed_l"],
                "child_fresh_l": section["draw_fresh_l"], "child_reclaimed_l": section["draw_reclaimed_l"],
                "allocated_fresh_l": fresh_total,
                "allocated_reclaimed_l": reclaimed_total,
                "remainder_fresh_l": section["usable_fresh_l"] - fresh_total,
                "remainder_reclaimed_l": section["usable_reclaimed_l"] - reclaimed_total,
                "reclaimed_ratio": section["reclaimed_ratio"],
            })
            held += remainder
    else:
        for row in channels["channels"]:
            channel_total = by_channel.pop(row["channel"], 0)
            remainder = row["usable_l"] - channel_total
            if remainder < 0:
                issues.append(issue("CHANNEL_UNBALANCED", row["source"]))
            ledgers.append({**row, "allocated_l": channel_total, "remainder_l": remainder + row["held_l"],
                            "inflow_fresh_l": row["inflow_l"], "inflow_reclaimed_l": 0,
                            "injected_fresh_l": 0, "injected_reclaimed_l": 0,
                            "loss_fresh_l": row["loss_l"], "loss_reclaimed_l": 0,
                            "child_fresh_l": row["child_inflow_l"], "child_reclaimed_l": 0,
                            "allocated_fresh_l": channel_total, "allocated_reclaimed_l": 0,
                            "remainder_fresh_l": remainder + row["held_l"], "remainder_reclaimed_l": 0,
                            "reclaimed_ratio": "0/1"})
            held += remainder
    if unknown_channels:
        issues.append(issue("CHANNEL_UNBALANCED"))

    losses = channels["loss_l"]
    supply = batch["supply_l"]
    if dual_mode:
        t0 = source_stage["totals"]
        total_input = supply + t0["reclaimed_admitted_l"] + t0["fresh_injected_l"]
    else:
        total_input = supply
    difference = total_input - losses - total_allocated - held
    overdrawn = any(
        row["allocated_fresh_l"] > row.get("inflow_fresh_l", 0) + row.get("injected_fresh_l", 0)
        or row["allocated_reclaimed_l"] > row.get("inflow_reclaimed_l", 0) + row.get("injected_reclaimed_l", 0)
        for row in ledgers
    )
    unbalanced = bool(difference or unknown_channels or overdrawn)

    totals = {"fresh_supply_l": supply, "reclaimed_admitted_l": 0, "reclaimed_withheld_l": 0,
              "fresh_injected_l": 0, "loss_fresh_l": losses, "loss_reclaimed_l": 0,
              "allocated_fresh_l": total_allocated, "allocated_reclaimed_l": 0,
              "remaining_fresh_l": held, "remaining_reclaimed_l": 0, "fresh_saved_l": 0}
    if dual_mode:
        t = source_stage["totals"]
        totals.update({
            "reclaimed_admitted_l": t["reclaimed_admitted_l"],
            "reclaimed_withheld_l": t["reclaimed_withheld_l"],
            "fresh_injected_l": t["fresh_injected_l"],
            "loss_fresh_l": t["loss_fresh_l"], "loss_reclaimed_l": t["loss_reclaimed_l"],
            "allocated_fresh_l": previous["tail"]["fresh_l"],
            "allocated_reclaimed_l": previous["tail"]["reclaimed_l"],
            "remaining_fresh_l": sum(r["remainder_fresh_l"] for r in ledgers) + channels["held_at_head_l"],
            "remaining_reclaimed_l": sum(r["remainder_reclaimed_l"] for r in ledgers),
            # 少取的清水 = 已启用再生水中真正替代清水的实配部分。
            "fresh_saved_l": previous["tail"]["reclaimed_l"],
        })
        recomputed = (supply + totals["fresh_injected_l"] + totals["reclaimed_admitted_l"]
                      - totals["loss_fresh_l"] - totals["loss_reclaimed_l"]
                      - totals["allocated_fresh_l"] - totals["allocated_reclaimed_l"]
                      - totals["remaining_fresh_l"] - totals["remaining_reclaimed_l"])
        if recomputed:
            unbalanced = True
            difference = recomputed

    return {"status": "DIFFERENCE" if unbalanced
            else "REVIEW" if issues else "MATCHED", "supply_l": supply, "loss_l": losses,
            "allocated_l": total_allocated, "remaining_l": held, "difference_l": difference,
            "ledgers": ledgers, "totals": totals, "issues": issues}
