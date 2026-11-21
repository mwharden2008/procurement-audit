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


VENDOR_LIST = {"start": re.compile(r'"approved_vendor_list":\s*\['),
               "entry": re.compile(r'\{"vendor_id":\s*"[^"]+"[^{}]*\}'),
               "name": "Approved Vendor List", "marker": '{"vendor_id"', "fields": ("vendor_id", "name", "status")}
IT_CATALOG = {"start": re.compile(r'"pre_approved_it_catalog":\s*\['),
              "entry": re.compile(r'\{"item":\s*"[^"]+"[^{}]*\}'),
              "name": "Pre-Approved IT Catalog", "marker": '{"item"', "fields": ("item", "vendor")}
BUDGET_TABLE = re.compile(r'"department_budgets_remaining_usd":\s*\{([^{}]*)\}')


class IncompleteReferenceData(RuntimeError):
    """The retrieved reference data is not complete enough to decide the request."""


def _list_piece(chunk, spec):
    """The part of one reference-data list that one chunk holds, or None."""
    text = chunk.get("chunk_text", "")
    start = spec["start"].search(text)
    body = text[start.end():] if start else text
    matches = list(spec["entry"].finditer(body))
    if not matches and not start:
        return None
    rest = body[matches[-1].end():] if matches else body
    closes = bool(matches) and rest.lstrip(" \t\r\n,").startswith("]")
    marker = spec["marker"]
    partial = "" if closes or marker not in rest else rest[rest.find(marker):].strip()
    return {"id": chunk.get("id"), "starts": bool(start), "closes": closes,
            "entries": [m.group(0) for m in matches], "partial": partial}


def reference_list(chunks, spec):
    """Reassemble one list from the reference data out of the retrieved chunks.

    Meko may split a list across chunks, so the pieces are joined end to end.
    The list counts as complete only when the chunk that opens the list was
    retrieved, each following piece overlaps the one before it (so nothing in
    between can be missing), and the last piece closes the list. Nothing here
    assumes how many entries there are.
    """
    name = spec["name"]
    pieces = [p for p in (_list_piece(c, spec) for c in chunks) if p]
    start = next((p for p in pieces if p["starts"]), None)
    if start is None:
        return {"complete": False, "entries": [], "source_chunks": [],
                "reason": f"the start of the {name} was not retrieved"}

    entries, partial, closed = list(start["entries"]), start["partial"], start["closes"]
    used = [start["id"]]
    while not closed:
        for piece in pieces:
            if piece["id"] in used or not piece["entries"]:
                continue
            first = piece["entries"][0]
            if first in entries:
                overlap = entries[entries.index(first):]
                if piece["entries"][:len(overlap)] != overlap:
                    continue
                new = piece["entries"][len(overlap):]
            elif partial and first.startswith(partial):
                new = piece["entries"]
            else:
                continue
            entries += new
            partial, closed = piece["partial"], piece["closes"]
            used.append(piece["id"])
            break
        else:
            return {"complete": False, "entries": _parse(entries, spec), "source_chunks": used,
                    "reason": (f"the retrieved text holds the start of the {name} and "
                               f"{len(entries)} entries, but not the rest of the list")}
    return {"complete": True, "entries": _parse(entries, spec), "source_chunks": used,
            "reason": f"the whole {name} was retrieved, from its start to its end"}


def vendor_list(chunks):
    return reference_list(chunks, VENDOR_LIST)


def catalog_list(chunks):
    return reference_list(chunks, IT_CATALOG)


def _parse(entries, spec):
    parsed = []
    for entry in entries:
        fields = dict(re.findall(r'"(\w+)":\s*"([^"]*)"', entry))
        parsed.append({k: fields.get(k) for k in spec["fields"]})
    return parsed


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
        if not is_blank(department):
            # R3 needs this figure. A blank department is rejected under R1 instead.
            table = next((m for c in chunks
                          for m in [BUDGET_TABLE.search(c.get("chunk_text", ""))] if m), None)
            facts["department_budget_missing"] = (
                f"the department budget table was retrieved but has no entry for '{department}'"
                if table else "the department budget table was not retrieved")
    else:
        facts["department_budget_remaining_usd"] = float(budget)
        facts["amount_is_greater_than_remaining_budget"] = amount > float(budget)
        facts["department_budget_source_chunk"] = source

    vendor = request.get("vendor") or ""
    status, source = find_in_chunks(
        rf'"name":\s*"{re.escape(vendor)}",\s*"status":\s*"(\w+)"', chunks)
    if status is not None:
        facts["vendor_status"] = status
        facts["vendor_status_source_chunk"] = source
    else:
        listing = vendor_list(chunks)
        facts["vendor_list_complete"] = listing["complete"]
        facts["vendor_list_check"] = listing["reason"]
        facts["vendor_list_source_chunks"] = listing["source_chunks"]
        if listing["complete"]:
            facts["vendor_status"] = "not on the list"
            facts["vendor_list_vendor_count"] = len(listing["entries"])
        else:
            facts["vendor_status"] = "unknown: not found in the part of the list that was retrieved"

    catalog = set()
    for chunk in chunks:
        text = chunk.get("chunk_text", "")
        catalog.update(re.findall(r'"item":\s*"([^"]+)"', text))
        catalog.update(item.strip() for item in re.findall(r'Item:\s*([^;\n]+);\s*Vendor:', text))
    facts["category_is_it_hardware_or_software"] = request.get("category") in IT_CATEGORIES
    if request.get("category") in IT_CATEGORIES:
        named = request.get("catalog_item")
        facts["pre_approved_it_catalog_items_retrieved"] = sorted(catalog)
        if is_blank(named):
            # No catalog item is named, so nothing can match: the catalog is not needed.
            facts["catalog_item_named"] = False
            facts["item_is_in_pre_approved_it_catalog"] = False
        elif named in catalog:
            facts["catalog_item_named"] = True
            facts["item_is_in_pre_approved_it_catalog"] = True
        else:
            # Absent from what was retrieved: it is only known to be absent
            # from the catalog if the whole catalog was retrieved.
            facts["catalog_item_named"] = True
            listing = catalog_list(chunks)
            facts["it_catalog_complete"] = listing["complete"]
            facts["it_catalog_check"] = listing["reason"]
            facts["it_catalog_source_chunks"] = listing["source_chunks"]
            if listing["complete"]:
                facts["item_is_in_pre_approved_it_catalog"] = False

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


def missing_reference_data(facts):
    """What the request needs from the reference data but did not get."""
    problems = []
    if facts.get("vendor_list_complete") is False:
        problems.append(f"R2: the vendor was not found and {facts['vendor_list_check']}, so it "
                        f"is not known whether the vendor is on the Approved Vendor List.")
    if "department_budget_missing" in facts:
        problems.append(f"R3: {facts['department_budget_missing']}, so it is not known "
                        f"whether the amount is within the department's budget.")
    if facts.get("it_catalog_complete") is False:
        problems.append(f"E4: the catalog item was not found and {facts['it_catalog_check']}, "
                        f"so it is not known whether the item is in the Pre-Approved IT Catalog.")
    return problems


def require_complete_reference_data(facts):
    """Stop the decision when the facts rest on part of the reference data.

    Covers the vendor list (R2), the department budget (R3) and the IT catalog
    (E4). When one is needed and was not retrieved in full, no decision is
    made: the request fails and can be retried, rather than being judged (or
    approved) on partial data, and the model never rules on those rules.
    """
    problems = missing_reference_data(facts)
    if problems:
        raise IncompleteReferenceData(
            "No decision was made because the reference data needed was not retrieved. "
            + " ".join(problems) + " Run the request again to retry the retrieval.")


def money(amount):
    return f"${amount:,.2f}"


def code_checks(facts):
    """Verdicts for the rules that the computed facts settle on their own.

    Returns {rule: {"applies": bool, "reason": str}}. A rule is left out when
    the facts cannot settle it, and the model's judgement stands for that rule.
    R6 (prohibited item) and E5 (conflict of interest) are always left to the model.
    A vendor missing from the list settles R2, and a named item missing from the
    IT catalog settles E4, only when the whole list was retrieved. When the
    data R2, R3 or E4 needs is missing, require_complete_reference_data stops
    the request before the model is asked.
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
    elif status == "not on the list" and facts.get("vendor_list_complete"):
        settle("R2", True, f"The vendor is not on the Approved Vendor List. The whole list "
                           f"({facts['vendor_list_vendor_count']} vendors) was retrieved and "
                           f"does not include it.")
    # A vendor missing from an incomplete list is never settled here: the
    # Policy agent stops the request instead (require_complete_reference_data).

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
    elif status == "not on the list" and facts.get("vendor_list_complete"):
        settle("E3", False, "The vendor is not on the Approved Vendor List, so it is not on probation.")

    if not facts["category_is_it_hardware_or_software"]:
        settle("E4", False, "The category is not IT hardware or software.")
    elif facts.get("catalog_item_named") is False:
        settle("E4", True, "The category is IT hardware or software and no Pre-Approved IT "
                           "Catalog item is named, so the item is not in the catalog.")
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
