"""Approver agent: records the final decision for one purchase request.

It is the third of three agents. It takes the Policy agent's rule checks and,
in the same Meko conversation:
  1. applies the policy's order: any reject rule means REJECT, otherwise any
     escalate rule means ESCALATE, otherwise APPROVE;
  2. names the reviewers for an escalation;
  3. writes the plain-language explanation from that final decision and the
     evidence for the rules that decided it, so the explanation and the
     decision cannot disagree. The Policy model's draft is kept in the Policy
     step of the trace but is not used;
  4. records the decision as its own step in the trace;
  5. stores a memory of the outcome for later decisions to find.

It makes no model call, so the final decision is always worked out in code.
"""

import json

from agents.intake_agent import message_id_of
from agents.rules import RULE_IDS, final_outcome

ROLE = "approver"


async def run(request, policy, meko, conversation_id):
    """Record the final decision and the memory. Returns the decision dict."""
    request_id = request["request_id"]
    decision = final_outcome(policy["rule_checks"], policy["model_overruled_by_code_checks"],
                             policy["tier"])
    decision["computed_facts"] = policy["computed_facts"]

    rules = ", ".join(decision["rules"]) or "no rules cited"
    message = await meko.add_message(
        conversation_id,
        input_text=json.dumps({"request_id": request_id,
                               "rule_checks": [policy["rule_checks"][rule] for rule in RULE_IDS
                                               if rule in policy["rule_checks"]]}),
        output_text=json.dumps(decision),
        reasoning=decision["explanation"],
        plan=[
            "Take the Policy agent's rule checks.",
            "Apply reject rules before escalate rules to reach the decision.",
            "Name a reviewer for each escalate rule that applies.",
            "Write the explanation for a reader outside Procurement and store a memory.",
        ],
        metadata={
            "agent_role": ROLE,
            "step": 3,
            "request_id": request_id,
            "decision": decision["decision"],
            "rules": decision["rules"],
            "reviewers": decision["reviewers"],
            "tier": decision["tier"],
        },
    )

    await meko.add_memory(
        conversation_id,
        text=(
            f"Purchase request {request_id} dated {request.get('request_date')}: "
            f"{request.get('requester')} ({request.get('department')}) requested "
            f"${request.get('amount_usd') or 0:,.2f} from {request.get('vendor')} for "
            f"{request.get('item')}. Decision: {decision['decision']} ({rules})."
        ),
        metadata={
            "request_id": request_id,
            "decision": decision["decision"],
            "requester": request.get("requester"),
            "vendor": request.get("vendor"),
            "amount_usd": request.get("amount_usd"),
            "request_date": request.get("request_date"),
            "recorded_by": ROLE,
        },
    )
    return decision, message_id_of(message)
