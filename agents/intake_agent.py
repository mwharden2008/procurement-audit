"""Intake agent: checks a purchase request and extracts its fields.

It is the first of three agents to handle a request. It opens the Meko
conversation that the Policy and Approver agents then write to, so the whole
decision sits in one trace.

Intake does not judge the request against policy. A blank required field is
listed here and left for the Policy agent to rule on (rule R1). Intake stops
the workflow only when the request cannot be read at all: no request ID, an
amount that is not a number, or a date that is not a date.
"""

import json
from datetime import date

from agents.facts import REQUIRED_FIELDS, is_blank

ROLE = "intake"
TEXT_FIELDS = ["request_id", "request_date", "requester", "department", "vendor", "item",
               "category", "catalog_item", "justification", "manager_signoff",
               "conflict_of_interest_note"]
FLAG_FIELDS = ["sole_source_justification", "conflict_of_interest_declared"]


class IntakeError(ValueError):
    """The request cannot be read well enough to assess."""


def extract(raw):
    """Return (fields, problems) for one raw request.

    Text is trimmed, the amount becomes a number, the quote count an integer
    and the yes/no fields true or false. Fields the request does not contain
    are left out, so a missing field stays missing.
    """
    fields, problems = {}, []
    for name in TEXT_FIELDS:
        if name in raw:
            value = raw[name]
            fields[name] = value.strip() if isinstance(value, str) else value

    if "amount_usd" in raw:
        amount = raw["amount_usd"]
        if amount is None or isinstance(amount, bool):
            fields["amount_usd"] = None
        else:
            try:
                fields["amount_usd"] = float(amount)
            except (TypeError, ValueError):
                problems.append(f"The amount {amount!r} is not a number.")

    quotes = raw.get("quotes_attached") or 0
    try:
        fields["quotes_attached"] = int(quotes)
    except (TypeError, ValueError):
        problems.append(f"The number of quotes {quotes!r} is not a whole number.")

    for name in FLAG_FIELDS:
        fields[name] = bool(raw.get(name))

    if is_blank(fields.get("request_id")):
        problems.append("The request has no request ID.")
    if not is_blank(fields.get("request_date")):
        try:
            date.fromisoformat(fields["request_date"])
        except (TypeError, ValueError):
            problems.append(f"The request date {fields['request_date']!r} is not a date (YYYY-MM-DD).")
    return fields, problems


async def run(raw, meko):
    """Open the trace, check the request and record the Intake step."""
    request_id = (raw.get("request_id") or "").strip() or "unknown request"
    conversation_id = await meko.start_conversation(
        title=f"{request_id}: {(raw.get('item') or '')[:60]}",
        metadata={"request_id": request_id, "agents": ["intake", "policy", "approver"]},
    )

    fields, problems = extract(raw)
    missing = [name for name in REQUIRED_FIELDS if is_blank(fields.get(name))]
    status = "invalid" if problems else "accepted"
    if problems:
        summary = "Intake could not read the request: " + " ".join(problems)
    elif missing:
        summary = (f"Intake extracted the request fields. Required fields left blank: "
                   f"{', '.join(missing)}. The Policy agent rules on these under R1.")
    else:
        summary = "Intake extracted the request fields. Every required field is filled in."

    result = {"status": status, "fields": fields, "missing_required_fields": missing,
              "problems": problems, "summary": summary}
    message = await meko.add_message(
        conversation_id,
        input_text=json.dumps(raw),
        output_text=json.dumps(result),
        reasoning=summary,
        plan=[
            "Open the Meko conversation for this request.",
            "Trim text, read the amount as a number and the quote count as a whole number.",
            "List any required field that is blank, for the Policy agent to rule on.",
        ],
        metadata={"agent_role": ROLE, "step": 1, "request_id": request_id, "status": status,
                  "missing_required_fields": missing},
    )
    result["conversation_id"] = conversation_id
    result["message_id"] = message_id_of(message)
    if problems:
        raise IntakeError(f"{request_id}: {summary}")
    return result


def message_id_of(message):
    if isinstance(message, dict):
        return message.get("message_id") or message.get("id")
    return None
