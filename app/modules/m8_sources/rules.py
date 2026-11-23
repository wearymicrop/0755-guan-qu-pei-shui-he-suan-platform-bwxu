from collections import defaultdict, deque

from app.evidence import issue, key, rows
from app.units import liters

FRESH = "fresh"
RECLAIMED = "reclaimed"
PLAN_A = "A_REPLENISH"
PLAN_B = "B_PROTECT"


def allocate_integers(total, proportions):
    """按比例把整数 total 拆成整数份，守恒；并列时把余量给靠前的桶。"""
    weights = [max(0, p) for p in proportions]
    weight_sum = sum(weights)
    if total <= 0 or weight_sum == 0:
        return [0 for _ in weights]
    floors = [total * w // weight_sum for w in weights]
    remainder = total - sum(floors)
    ranked = sorted(range(len(weights)), key=lambda i: (-weights[i], i))
    for index in ranked[:remainder]:
        floors[index] += 1
    return floors


def read_restrictions(data, active_outlets):
    records, blocked, issues = [], set(), []
    seen = set()
    for _row, source in rows(data, "restrictions"):
        try:
            outlet = key(_row["outlet"])
            purpose = key(_row.get("purpose", "受限用水"))
        except (KeyError, TypeError, ValueError):
            issues.append(issue("BAD_RESTRICTION", source))
            continue
        record = {"outlet": outlet, "purpose": purpose, "source": source}
        records.append(record)
        if outlet in seen:
            issues.append(issue("BAD_RESTRICTION", source))
        seen.add(outlet)
        if outlet not in active_outlets:
            issues.append(issue("UNKNOWN_RESTRICTION", source))
        else:
            blocked.add(outlet)
    return records, blocked, issues


def read_sources(data, reachable, subtree_blocked):
    decisions, issues = [], []
    names = set()
    for _row, source in rows(data, "sources"):
        try:
            name = key(_row["source"])
            kind = _row["kind"]
            if kind not in (FRESH, RECLAIMED):
                raise ValueError
            channel = key(_row["channel"])
            offered = liters(_row["offered"], _row["unit"])
        except (KeyError, TypeError, ValueError):
            issues.append(issue("BAD_SOURCE", source))
            continue
        if name in names:
            issues.append(issue("BAD_SOURCE", source))
        names.add(name)
        if channel not in reachable:
            issues.append(issue("SOURCE_ROUTE_BLOCKED", source))
            decisions.append({"source": name, "kind": kind, "channel": channel, "offered_l": offered,
                              "admitted_l": 0, "plan": PLAN_B, "state": "route_blocked", "evidence": source})
            continue
        if kind == RECLAIMED and subtree_blocked[channel]:
            # 方案B：受限斗口在同一渠系下游，缓注保供，余量留账。
            decisions.append({"source": name, "kind": kind, "channel": channel, "offered_l": offered,
                              "admitted_l": 0, "plan": PLAN_B, "state": "withheld", "evidence": source})
        else:
            # 方案A：立即补水，替代清水。
            decisions.append({"source": name, "kind": kind, "channel": channel, "offered_l": offered,
                              "admitted_l": offered, "plan": PLAN_A, "state": "admitted", "evidence": source})
    return decisions, issues


def run(_data, previous):
    data = _data or {}
    channel_rows = previous["channels"]["channels"]
    ready_names = [row["channel"] for row in channel_rows]
    reachable = set(ready_names)
    children = defaultdict(list)
    for row in channel_rows:
        if row["parent"] is not None:
            children[row["parent"]].append(row["channel"])
    for name in children:
        children[name].sort()

    # 各斗口所在渠段与受限登记。
    outlet_channel = {row["outlet"]: row["channel"] for row in previous["rights"]["active"]}
    restrictions, blocked_outlets, issues = (
        read_restrictions(data, set(outlet_channel)) if data.get("restrictions") else ([], set(), [])
    )
    restricted_channels = {outlet_channel[o] for o in blocked_outlets if o in outlet_channel}

    # 每个渠段子树是否含受限斗口（含本段）；后序遍历保证每段都完整求值。
    subtree_blocked = {}
    for name in reversed(ready_names):  # ready_names 为 BFS 序，逆序即子先于父
        subtree_blocked[name] = name in restricted_channels or any(
            subtree_blocked[child] for child in children.get(name, [])
        )

    decisions, source_issues = (
        read_sources(data, reachable, subtree_blocked) if data.get("sources") else ([], [])
    )
    issues.extend(source_issues)

    root = previous["batches"]["root"]
    supply = previous["batches"]["supply_l"]
    injections = defaultdict(lambda: [0, 0])  # [fresh, reclaimed] 整升
    for decision in decisions:
        if decision["state"] == "admitted":
            slot = 0 if decision["kind"] == FRESH else 1
            injections[decision["channel"]][slot] += decision["admitted_l"]

    by_name = {row["channel"]: row for row in channel_rows}
    # 渠首物理入流须等于清水供水加渠首汇入；非渠首汇入叠加在该段账内。
    root_fresh, root_reclaimed = injections[root]
    if data.get("sources") and root_fresh + root_reclaimed and by_name[root]["inflow_l"] != supply + root_fresh + root_reclaimed:
        issues.append(issue("SOURCE_HEAD_MISMATCH", by_name[root]["source"]))

    sections = {}
    pending = {}  # 子渠在父段出流侧分摊到的待取流（清水, 再生水）
    queue = deque([name for name in ready_names if by_name[name]["parent"] is None])
    while queue:
        name = queue.popleft()
        row = by_name[name]
        inject_fresh, inject_reclaimed = injections[name]
        if row["parent"] is None:
            inflow_fresh, inflow_reclaimed = supply + root_fresh, root_reclaimed
        else:
            inflow_fresh, inflow_reclaimed = pending.pop(name)
        loss_fresh, loss_reclaimed = allocate_integers(
            row["loss_l"], [inflow_fresh + inject_fresh, inflow_reclaimed + inject_reclaimed]
        ) if row["loss_l"] else (0, 0)
        after_fresh = inflow_fresh + inject_fresh - loss_fresh
        after_reclaimed = inflow_reclaimed + inject_reclaimed - loss_reclaimed
        child_names = children.get(name, [])
        child_draw = {child: by_name[child]["inflow_l"] for child in child_names}
        draw_total = sum(child_draw.values())
        draw_fresh, draw_reclaimed = allocate_integers(draw_total, [after_fresh, after_reclaimed])
        for child in child_names:
            pending[child] = tuple(
                allocate_integers(child_draw[child], [draw_fresh, draw_reclaimed])
            ) if child_draw[child] else (0, 0)
        usable_fresh = after_fresh - draw_fresh
        usable_reclaimed = after_reclaimed - draw_reclaimed
        usable = usable_fresh + usable_reclaimed
        sections[name] = {
            "channel": name, "parent": row["parent"], "source": row["source"],
            "inflow_fresh_l": inflow_fresh, "inflow_reclaimed_l": inflow_reclaimed,
            "injected_fresh_l": inject_fresh, "injected_reclaimed_l": inject_reclaimed,
            "loss_fresh_l": loss_fresh, "loss_reclaimed_l": loss_reclaimed,
            "draw_fresh_l": draw_fresh, "draw_reclaimed_l": draw_reclaimed,
            "usable_fresh_l": usable_fresh, "usable_reclaimed_l": usable_reclaimed,
            "usable_l": usable, "held_l": row["held_l"],
            "reclaimed_ratio": (f"{usable_reclaimed}/{usable}" if usable else "0/1"),
            "subtree_restricted": subtree_blocked.get(name, False),
            "mix_blocked": False,
        }
        queue.extend(child_names)

    # 硬护栏：受限斗口所在段一旦带再生水成分即阻断，方案B仍漏混时留证。
    blocked_channels = set()
    for name in restricted_channels:
        section = sections.get(name)
        if section and section["usable_reclaimed_l"] > 0:
            section["mix_blocked"] = True
            blocked_channels.add(name)
            line = next((r["source"] for r in restrictions if outlet_channel.get(r["outlet"]) == name), None)
            issues.append(issue("RESTRICTED_CONTACT", *([s for s in (line, by_name[name]["source"]) if s])))

    blocked_outlet_rows = sorted(
        ({"outlet": outlet, "channel": outlet_channel[outlet],
          "purpose": next(r["purpose"] for r in restrictions if r["outlet"] == outlet)}
         for outlet in blocked_outlets if outlet_channel[outlet] in blocked_channels),
        key=lambda row: row["outlet"],
    )
    section_list = [sections[name] for name in ready_names]
    totals = {
        "fresh_supply_l": supply,
        "reclaimed_offered_l": sum(d["offered_l"] for d in decisions if d["kind"] == RECLAIMED),
        "reclaimed_admitted_l": sum(d["admitted_l"] for d in decisions if d["kind"] == RECLAIMED),
        "reclaimed_withheld_l": sum(
            d["offered_l"] - d["admitted_l"] for d in decisions if d["kind"] == RECLAIMED
        ),
        "fresh_injected_l": sum(d["admitted_l"] for d in decisions if d["kind"] == FRESH),
        "loss_fresh_l": sum(s["loss_fresh_l"] for s in section_list),
        "loss_reclaimed_l": sum(s["loss_reclaimed_l"] for s in section_list),
        "usable_fresh_l": sum(s["usable_fresh_l"] for s in section_list),
        "usable_reclaimed_l": sum(s["usable_reclaimed_l"] for s in section_list),
    }
    return {"decisions": decisions, "restrictions": restrictions, "sections": section_list,
            "blocked_outlets": blocked_outlet_rows, "totals": totals, "issues": issues}
