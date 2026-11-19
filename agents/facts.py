"""Facts worked out in code before the model is asked to judge the rules.

Language models are unreliable at arithmetic and at finding one value in a
long list, so the amount comparisons, the budget and vendor lookups and the
split-purchase sums are done here. Budget and vendor status are read from the
text Meko retrieved, and the ID of the chunk each came from is kept so the
trace shows the source.
"""

import re
from datetime import date

IT_CATEGORIES = {"it_hardware", "software"}
REQUIRED_FIELDS = ["requester", "department", "vendor", "item", "category",
                   "amount_usd", "request_date", "justification"]


def tier(amount):
    if amount < 1000:
        return "T1"
    if amount < 10000:
        return "T2"
    if amount < 50000:
        return "T3"
    return "T4"


def is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def find_in_chunks(pattern, chunks):
    """Return (first captured group, chunk ID) for the first chunk that matches."""
    for chunk in chunks:
        match = re.search(pattern, chunk.get("chunk_text", ""))
        if match:
            return match.group(1), chunk.get("id")
    return None, None


def related_requests(request, memories):
    """Earlier requests by the same requester to the same vendor, from Meko memory.

    Uses the structured metadata the agent stores with each decision memory.
    Keeps the newest memory for each request ID and ignores the current request.
    """
    today = date.fromisoformat(request["request_date"])
    newest = {}
    for memory in memories:
        meta = memory.get("metadata") or {} if isinstance(memory, dict) else {}
        if not all(key in meta for key in ("request_id", "requester", "vendor",
                                           "amount_usd", "request_date")):
            continue
        if meta["request_id"] == request["request_id"]:
            continue
        if meta["requester"] != request.get("requester") or meta["vendor"] != request.get("vendor"):
            continue
        days = (today - date.fromisoformat(meta["request_date"])).days
        if not 0 <= days <= 7:
            continue
        if days == 0 and meta["request_id"] > request["request_id"]:
            continue
        current = newest.get(meta["request_id"])
        if current is None or memory.get("created_at", "") > current["created_at"]:
            newest[meta["request_id"]] = {
                "request_id": meta["request_id"],
                "request_date": meta["request_date"],
                "amount_usd": float(meta["amount_usd"]),
                "days_before": days,
                "created_at": memory.get("created_at", ""),
                "memory_id": memory.get("id"),
            }
    return sorted(newest.values(), key=lambda r: r["request_id"])


def compute_facts(request, chunks, memories):
    amount = request.get("amount_usd")
    facts = {
        "missing_required_fields": [f for f in REQUIRED_FIELDS if is_blank(request.get(f))],
        "manager_signoff_recorded": not is_blank(request.get("manager_signoff")),
        "quotes_attached": request.get("quotes_attached", 0),
        "fewer_than_three_quotes": request.get("quotes_attached", 0) < 3,
        "sole_source_justification_attached": bool(request.get("sole_source_justification")),
        "conflict_of_interest_declared": bool(request.get("conflict_of_interest_declared")),
    }
    if amount is None:
        return facts

    facts.update({
        "amount_usd": amount,
        "tier": tier(amount),
        "amount_is_1000_or_more": amount >= 1000,
        "amount_is_10000_or_more": amount >= 10000,
        "amount_is_50000_or_more": amount >= 50000,
        "amount_is_more_than_2500": amount > 2500,
    })

    department = request.get("department") or ""
    budget, source = find_in_chunks(rf'"{re.escape(department)}":\s*(\d+(?:\.\d+)?)', chunks)
    if budget is None:
        facts["department_budget"] = "not found in the retrieved reference data"
    else:
        facts["department_budget_remaining_usd"] = float(budget)
        facts["amount_is_greater_than_remaining_budget"] = amount > float(budget)
        facts["department_budget_source_chunk"] = source

    vendor = request.get("vendor") or ""
    status, source = find_in_chunks(
        rf'"name":\s*"{re.escape(vendor)}",\s*"status":\s*"(\w+)"', chunks)
    seen = {v for c in chunks for v in re.findall(r'"vendor_id":\s*"([^"]+)"', c.get("chunk_text", ""))}
    if status is None:
        facts["vendor_status"] = (
            f"vendor not found among the {len(seen)} vendors in the retrieved Approved Vendor List")
    else:
        facts["vendor_status"] = status
        facts["vendor_status_source_chunk"] = source

    catalog = set()
    for chunk in chunks:
        text = chunk.get("chunk_text", "")
        catalog.update(re.findall(r'"item":\s*"([^"]+)"', text))
        catalog.update(item.strip() for item in re.findall(r'Item:\s*([^;\n]+);\s*Vendor:', text))
    facts["category_is_it_hardware_or_software"] = request.get("category") in IT_CATEGORIES
    if request.get("category") in IT_CATEGORIES:
        if catalog:
            facts["pre_approved_it_catalog_items_retrieved"] = sorted(catalog)
            facts["item_is_in_pre_approved_it_catalog"] = request.get("catalog_item") in catalog
        else:
            facts["pre_approved_it_catalog"] = "not found in the retrieved data"

    related = related_requests(request, memories)
    combined = amount + sum(r["amount_usd"] for r in related)
    highest_alone = max([tier(amount)] + [tier(r["amount_usd"]) for r in related])
    facts["earlier_requests_same_requester_and_vendor_within_7_days"] = [
        {k: r[k] for k in ("request_id", "request_date", "amount_usd", "days_before", "memory_id")}
        for r in related
    ]
    if related:
        facts["combined_amount_usd"] = combined
        facts["combined_tier"] = tier(combined)
        facts["highest_tier_of_any_single_request"] = highest_alone
        facts["combined_tier_is_higher_than_each_request_alone"] = tier(combined) > highest_alone
    return facts


def money(amount):
    return f"${amount:,.2f}"


def code_checks(facts):
    """Verdicts for the rules that the computed facts settle on their own.

    Returns {rule: {"applies": bool, "reason": str}}. A rule is left out when
    the facts cannot settle it, and the model's judgement stands for that rule.
    R6 (prohibited item) and E5 (conflict of interest) are always left to the model.
    """
    checks = {}

    def settle(rule, applies, reason):
        checks[rule] = {"applies": bool(applies), "reason": reason}

    missing = facts["missing_required_fields"]
    settle("R1", missing, f"Missing required fields: {', '.join(missing)}." if missing
           else "Every required field is filled in.")
    if "amount_usd" not in facts:
        return checks
    amount, level = facts["amount_usd"], facts["tier"]

    status = facts["vendor_status"]
    if status in ("approved", "probation"):
        settle("R2", False, f"The vendor is on the Approved Vendor List with status '{status}'.")
    elif status == "suspended":
        settle("R2", True, "The vendor's status on the Approved Vendor List is 'suspended'.")
    # A vendor that was not found is left to the model: the retrieved text
    # may not hold the whole vendor list, so code cannot be sure it is absent.

    if "department_budget_remaining_usd" in facts:
        budget = facts["department_budget_remaining_usd"]
        over = facts["amount_is_greater_than_remaining_budget"]
        settle("R3", over, f"{money(amount)} is {'more than' if over else 'within'} the "
                           f"department's remaining budget of {money(budget)}.")

    signed = facts["manager_signoff_recorded"]
    if not facts["amount_is_1000_or_more"]:
        settle("R4", False, f"{money(amount)} is under $1,000, so no manager sign-off is needed.")
    else:
        settle("R4", not signed, f"{money(amount)} is $1,000 or more and a manager sign-off "
                                 f"{'is' if signed else 'is not'} recorded.")

    quotes = facts["quotes_attached"]
    sole = facts["sole_source_justification_attached"]
    if not facts["amount_is_10000_or_more"]:
        settle("R5", False, f"{money(amount)} is under $10,000, so three quotes are not required.")
        settle("E2", False, f"{money(amount)} is under $10,000, so the sole-source rule does not apply.")
    else:
        settle("R5", quotes < 3 and not sole,
               f"{money(amount)} is $10,000 or more with {quotes} quote(s) attached and "
               f"{'a' if sole else 'no'} sole-source justification.")
        settle("E2", sole, f"{money(amount)} is $10,000 or more and "
                           f"{'a' if sole else 'no'} sole-source justification is attached.")

    big = facts["amount_is_50000_or_more"]
    settle("E1", big, f"{money(amount)} is {'$50,000 or more' if big else 'under $50,000'}.")

    if status in ("approved", "probation", "suspended"):
        applies = status == "probation" and facts["amount_is_more_than_2500"]
        settle("E3", applies, f"The vendor's status is '{status}' and {money(amount)} is "
                              f"{'more than' if facts['amount_is_more_than_2500'] else 'not more than'} $2,500.")

    if not facts["category_is_it_hardware_or_software"]:
        settle("E4", False, "The category is not IT hardware or software.")
    elif "item_is_in_pre_approved_it_catalog" in facts:
        listed = facts["item_is_in_pre_approved_it_catalog"]
        settle("E4", not listed, f"The category is IT hardware or software and the item "
                                 f"{'is' if listed else 'is not'} in the Pre-Approved IT Catalog.")

    related = facts["earlier_requests_same_requester_and_vendor_within_7_days"]
    if not related:
        settle("E6", False, "Meko memory holds no earlier request by this requester to this "
                            "vendor in the previous 7 days.")
    else:
        ids = ", ".join(r["request_id"] for r in related)
        higher = facts["combined_tier_is_higher_than_each_request_alone"]
        settle("E6", higher,
               f"With {ids}, the combined amount is {money(facts['combined_amount_usd'])} "
               f"(tier {facts['combined_tier']}). The highest tier of any single request is "
               f"{facts['highest_tier_of_any_single_request']}, so the combined tier "
               f"{'is' if higher else 'is not'} higher.")
    return checks
