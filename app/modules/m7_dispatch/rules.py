def run(data, previous):
    batch = previous["batches"]
    balance = previous["balance"]
    source_stage = previous.get("sources")
    dual_mode = bool(data.get("sources") or data.get("restrictions"))
    routes = {row["channel"]: row["source"] for row in balance["ledgers"]}
    source_refs = {}
    if dual_mode:
        source_refs = {d["source"]: d["evidence"] for d in source_stage["decisions"]}
    state = "ready" if balance["status"] == "MATCHED" else "held"
    receipts = []
    for row in previous["tail"]["allocations"]:
        if row["allocated_l"]:
            provenance = [row["source"]]
            if row["channel"] in routes:
                provenance.append(routes[row["channel"]])
            if dual_mode:
                provenance.extend(
                    ref for ref in (source_refs.get(d["source"]) for d in source_stage["decisions"]
                                    if d["channel"] == row["channel"] and d["state"] == "admitted")
                    if ref is not None
                )
            receipts.append({"receipt": f"{batch['batch']}/{row['outlet']}", "outlet": row["outlet"],
                             "channel": row["channel"], "allocated_l": row["allocated_l"],
                             "fresh_l": row["fresh_l"], "reclaimed_l": row["reclaimed_l"],
                             "state": state, "sources": provenance})
    totals = balance["totals"]
    return {"state": state, "receipts": receipts,
            "receipt_l": sum(row["allocated_l"] for row in receipts),
            "receipt_fresh_l": totals["allocated_fresh_l"],
            "receipt_reclaimed_l": totals["allocated_reclaimed_l"],
            "fresh_saved_l": totals["fresh_saved_l"],
            "issues": balance["issues"]}
