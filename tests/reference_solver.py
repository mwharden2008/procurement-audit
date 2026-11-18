"""Reference solver for policy PROC-001.

Applies the written rules deterministically, with no LLM, and compares the
result with data/expected_decisions.json. Use it to check the sample data and,
later, to score what the agents decide.

Run from the repository root:  python tests/reference_solver.py
"""

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = ["requester", "department", "vendor", "item", "category",
            "amount_usd", "request_date", "justification"]
REVIEWERS = {"E1": "Finance Director", "E2": "Procurement Manager",
             "E3": "Procurement Manager", "E4": "IT Security",
             "E5": "Compliance Officer", "E6": "Procurement Manager"}


def tier(amount):
    if amount < 1000:
        return 1
    if amount < 10000:
        return 2
    if amount < 50000:
        return 3
    return 4


def is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def decide(req, ref, earlier):
    """Return (decision, rules) for one request.

    `earlier` holds the requests dated before this one, for rule E6.
    """
    vendors = {v["name"]: v for v in ref["approved_vendor_list"]}
    catalog = {c["item"] for c in ref["pre_approved_it_catalog"]}
    budgets = ref["department_budgets_remaining_usd"]
    amount = req.get("amount_usd")
    vendor = vendors.get(req.get("vendor"))

    reject = []
    if any(is_blank(req.get(field)) for field in REQUIRED):
        reject.append("R1")
    if vendor is None or vendor["status"] == "suspended":
        reject.append("R2")
    if amount is not None:
        if amount > budgets.get(req.get("department"), 0):
            reject.append("R3")
        if amount >= 1000 and is_blank(req.get("manager_signoff")):
            reject.append("R4")
        if (amount >= 10000 and req.get("quotes_attached", 0) < 3
                and not req.get("sole_source_justification")):
            reject.append("R5")
    if req.get("category") in ref["prohibited_categories"]:
        reject.append("R6")
    if reject:
        return "REJECT", reject

    escalate = []
    if amount >= 50000:
        escalate.append("E1")
    if amount >= 10000 and req.get("sole_source_justification"):
        escalate.append("E2")
    if vendor["status"] == "probation" and amount > 2500:
        escalate.append("E3")
    if (req["category"] in ref["it_categories"]
            and req.get("catalog_item") not in catalog):
        escalate.append("E4")
    if req.get("conflict_of_interest_declared"):
        escalate.append("E5")

    today = date.fromisoformat(req["request_date"])
    related = [
        e for e in earlier
        if e["requester"] == req["requester"] and e["vendor"] == req["vendor"]
        and 0 <= (today - date.fromisoformat(e["request_date"])).days <= 7
    ]
    if related:
        combined = amount + sum(e["amount_usd"] for e in related)
        highest_alone = max(tier(amount), *(tier(e["amount_usd"]) for e in related))
        if tier(combined) > highest_alone:
            escalate.append("E6")

    if escalate:
        return "ESCALATE", escalate
    return "APPROVE", []


def main():
    ref = json.loads((ROOT / "data/reference_data.json").read_text())
    requests = json.loads((ROOT / "data/purchase_requests.json").read_text())
    expected = {d["request_id"]: d for d in json.loads(
        (ROOT / "data/expected_decisions.json").read_text())["decisions"]}

    ordered = sorted(requests, key=lambda r: (r["request_date"], r["request_id"]))
    failures = 0
    seen = []
    for req in ordered:
        decision, rules = decide(req, ref, seen)
        seen.append(req)
        want = expected[req["request_id"]]
        ok = decision == want["decision"] and rules == want["rules"]
        if decision == "ESCALATE":
            reviewers = sorted({REVIEWERS[r] for r in rules})
            ok = ok and reviewers == sorted(want.get("reviewers", []))
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {req['request_id']} {decision:<8} {','.join(rules)}")

    missing = set(expected) - {r["request_id"] for r in requests}
    print(f"\n{len(ordered) - failures} of {len(ordered)} match the answer key")
    if missing:
        print(f"In the answer key but not in the requests: {sorted(missing)}")
    return 1 if failures or missing else 0


if __name__ == "__main__":
    sys.exit(main())
