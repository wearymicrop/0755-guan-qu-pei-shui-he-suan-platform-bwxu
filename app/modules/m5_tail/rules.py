from collections import defaultdict
from fractions import Fraction


def allocate_integers(total, proportions):
    """按比例拆分整数 total，守恒；余数给比例大的桶，并列时给靠前桶。"""
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


def distribute(items):
    targets = [Fraction(row["target_units"]) for row in items]
    floors = [int(target) for target in targets]
    remainder = [target - floor for target, floor in zip(targets, floors)]
    ranked = sorted(range(len(items)), key=lambda i: (-remainder[i], items[i]["priority"], items[i]["outlet"]))
    count = int(sum(targets)) - sum(floors)
    awarded = set(ranked[:count])
    return [(floor, remainder[index], index in awarded) for index, floor in enumerate(floors)]


def split_sources(allocations, sections):
    """按渠段混合比例把每段实配拆为清水/再生水，整升守恒：
    先逐斗口按再生水比例算份额并落整，再用最大余数补齐段内再生水总量。"""
    if sections is None:
        for row in allocations:
            row["fresh_l"], row["reclaimed_l"] = row["allocated_l"], 0
        return allocations
    mix = {s["channel"]: (s["usable_fresh_l"], s["usable_reclaimed_l"], s["usable_l"]) for s in sections}
    grouped = defaultdict(list)
    for row in allocations:
        grouped[row["channel"]].append(row)
    for channel, rows_ in grouped.items():
        fresh_share, reclaimed_share, usable_total = mix[channel]
        total = sum(row["allocated_l"] for row in rows_)
        if total == 0 or usable_total == 0:
            for row in rows_:
                row["fresh_l"], row["reclaimed_l"] = 0, 0
            continue
        target_reclaimed = total * reclaimed_share // usable_total
        floors = [row["allocated_l"] * reclaimed_share // usable_total for row in rows_]
        leftovers = [
            Fraction(row["allocated_l"] * reclaimed_share, usable_total) - floor
            for row, floor in zip(rows_, floors)
        ]
        extra = target_reclaimed - sum(floors)
        ranked = sorted(range(len(rows_)), key=lambda i: (-leftovers[i], rows_[i]["priority"], rows_[i]["outlet"]))
        for index in ranked[:extra]:
            floors[index] += 1
        for row, reclaimed_part in zip(rows_, floors):
            row["reclaimed_l"] = min(reclaimed_part, row["allocated_l"])
            row["fresh_l"] = row["allocated_l"] - row["reclaimed_l"]
    return allocations


def run(data, previous):
    quota = previous["quotas"]
    quantum = quota["quantum_l"]
    grouped, allocations = defaultdict(list), []
    for row in quota["quotas"]:
        grouped[row["channel"]].append(row)
    for items in grouped.values():
        for row, (floor, remainder, awarded) in zip(items, distribute(items)):
            allocations.append({**row, "floor_l": floor * quantum, "remainder_units": str(remainder),
                                "tail_l": awarded * quantum, "allocated_l": (floor + awarded) * quantum})
    sections = previous["sources"]["sections"] if (data.get("sources") or data.get("restrictions")) else None
    split_sources(allocations, sections)
    return {"allocations": allocations, "allocated_l": sum(row["allocated_l"] for row in allocations),
            "fresh_l": sum(row["fresh_l"] for row in allocations),
            "reclaimed_l": sum(row["reclaimed_l"] for row in allocations),
            "tail_l": sum(row["tail_l"] for row in allocations), "issues": []}
