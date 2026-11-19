"""Policy agent: decides one purchase request and records why.

For each request the agent:
  1. opens a Meko conversation, which becomes the trace for the decision;
  2. retrieves the policy rules and reference data from Meko knowledge;
  3. searches Meko memory for earlier requests by the same requester,
     and works out amounts, budget, vendor status and sums in code;
  4. asks the model to check every rule, using only what was retrieved,
     and works out the decision from those checks in code;
  5. records the decision, its reasoning and token use in the trace;
  6. stores a memory of the outcome for later decisions to find.
"""

import json

from agents.facts import code_checks, compute_facts

SYSTEM_PROMPT = """You are the Policy agent for procurement at Harbor Ridge Distribution.

Assess one purchase request. Use only the policy text, reference data,
computed facts and memories given in the message. Do not rely on outside
knowledge of procurement.

The COMPUTED FACTS block holds arithmetic and lookups already done in code:
amount comparisons, the tier, the department budget, the vendor's status and
any earlier requests by the same requester to the same vendor. Rely on these
facts. Do not redo the arithmetic or override them.

The CODE RULE CHECKS block gives the verdict for each rule that those facts
settle on their own. For every rule listed there, give the same verdict. Use
your own judgement only for rules that are not listed.

Check every rule in the policy, one at a time: R1 to R6 and E1 to E6. For each
rule, say whether its condition is met and give the specific fact that settles
it. Mark a rule as applying only when its condition is fully met. A rule you
considered and ruled out does not apply.

A vendor reported as not found in the Approved Vendor List is not on the
list. Treat a blank or missing field as missing.

The system works out the final decision from your rule checks: any reject rule
that applies means REJECT, otherwise any escalate rule that applies means
ESCALATE, otherwise APPROVE. Write the explanation to match that outcome, for a
reader outside Procurement: plain sentences, the facts that mattered, no
jargon. Mention only rules that apply. Call record_decision exactly once."""

RULE_IDS = ["R1", "R2", "R3", "R4", "R5", "R6", "E1", "E2", "E3", "E4", "E5", "E6"]
REVIEWERS = {
    "E1": "Finance Director", "E2": "Procurement Manager",
    "E3": "Procurement Manager", "E4": "IT Security",
    "E5": "Compliance Officer", "E6": "Procurement Manager",
}

DECISION_TOOL = {
    "name": "record_decision",
    "description": "Record the rule checks for this purchase request.",
    "input_schema": {
        "type": "object",
        "properties": {
            "rule_checks": {
                "type": "array",
                "description": "One entry for every rule, R1 to R6 and E1 to E6.",
                "items": {
                    "type": "object",
                    "properties": {
                        "rule": {"type": "string", "enum": RULE_IDS},
                        "applies": {"type": "boolean"},
                        "evidence": {
                            "type": "string",
                            "description": "The fact that shows the rule does or does not apply.",
                        },
                    },
                    "required": ["rule", "applies", "evidence"],
                },
            },
            "tier": {"type": "string", "enum": ["T1", "T2", "T3", "T4"]},
            "explanation": {
                "type": "string",
                "description": "Two to four plain sentences a non-specialist can follow.",
            },
        },
        "required": ["rule_checks", "tier", "explanation"],
    },
}


def resolve(findings, verified=None):
    """Turn the model's rule checks into a decision, in the policy's order.

    `verified` holds the code's verdicts for rules the computed facts settle.
    Where the model disagrees with one, the code's verdict is used and the
    disagreement is recorded, so an auditor can see both.
    """
    verified = verified or {}
    model = {c["rule"]: c for c in findings["rule_checks"] if c["rule"] in RULE_IDS}
    checks, overrides = {}, []
    for rule in RULE_IDS:
        if rule in verified:
            said = model.get(rule, {}).get("applies")
            if said is not None and said != verified[rule]["applies"]:
                overrides.append({
                    "rule": rule, "model_said": said, "code_check_says": verified[rule]["applies"],
                    "model_evidence": model[rule]["evidence"], "reason": verified[rule]["reason"],
                })
            checks[rule] = {"rule": rule, "applies": verified[rule]["applies"],
                            "evidence": verified[rule]["reason"], "decided_by": "code check"}
        elif rule in model:
            checks[rule] = {**model[rule], "decided_by": "model"}

    applied = [rule for rule in RULE_IDS if checks.get(rule, {}).get("applies")]
    reject = [rule for rule in applied if rule.startswith("R")]
    escalate = [rule for rule in applied if rule.startswith("E")]
    if reject:
        decision, rules = "REJECT", reject
    elif escalate:
        decision, rules = "ESCALATE", escalate
    else:
        decision, rules = "APPROVE", []
    reviewers = sorted({REVIEWERS[rule] for rule in rules if rule in REVIEWERS})

    explanation = findings["explanation"]
    if overrides:
        # The model's wording may describe a verdict that was overruled, so
        # the explanation is rebuilt from the evidence for the final rules.
        outcome = {"REJECT": "This request is rejected.",
                   "ESCALATE": f"This request is sent to {' and '.join(reviewers)} for review.",
                   "APPROVE": "This request is approved. No reject or escalate rule applies."}[decision]
        explanation = " ".join([outcome] + [checks[rule]["evidence"] for rule in rules])
    return {
        "decision": decision,
        "rules": rules,
        "reviewers": reviewers,
        "tier": findings["tier"],
        "facts_used": [f"{rule}: {checks[rule]['evidence']}" for rule in rules],
        "explanation": explanation,
        "rule_checks": [checks[rule] for rule in RULE_IDS if rule in checks],
        "rules_not_checked": [rule for rule in RULE_IDS if rule not in checks],
        "model_overruled_by_code_checks": overrides,
    }


def knowledge_queries(request):
    """The lookups the agent makes for every request, plus request-specific ones."""
    queries = [
        "required information a purchase request must include",
        "approval tiers by amount: manager sign-off and competitive quotes",
        "reject rules R1 to R6",
        "escalate rules E1 to E6 and their reviewers",
        "order of evaluation: reject rules take priority over escalate rules",
        f"department budgets remaining for {request.get('department') or 'the department'}",
        f"{request.get('vendor') or 'vendor'} vendor status on the Approved Vendor List",
        "vendors with status probation or suspended",
    ]
    if request.get("category") in ("it_hardware", "software"):
        queries.append("Pre-Approved IT Catalog items")
    return queries


def memory_text(item):
    if isinstance(item, dict):
        return item.get("memory") or item.get("text") or json.dumps(item)
    return str(item)


def build_user_message(request, chunks, memories, facts, verified):
    parts = ["PURCHASE REQUEST", json.dumps(request, indent=2), "",
             "COMPUTED FACTS", json.dumps(facts, indent=2), "",
             "CODE RULE CHECKS", json.dumps(verified, indent=2), "",
             "RETRIEVED POLICY AND REFERENCE DATA"]
    for number, chunk in enumerate(chunks, start=1):
        parts += [f"[K{number}]", chunk["chunk_text"], ""]
    parts.append("MEMORIES OF EARLIER REQUESTS")
    if memories:
        parts += [f"[M{number}] {memory_text(m)}" for number, m in enumerate(memories, start=1)]
    else:
        parts.append("None found.")
    return "\n".join(parts)


async def decide(request, meko, llm, model):
    """Decide one request and write its trace to Meko. Returns a record dict."""
    request_id = request["request_id"]
    conversation_id = await meko.start_conversation(
        title=f"{request_id}: {request.get('item', '')[:60]}",
        metadata={"request_id": request_id, "agent_role": "policy"},
    )

    # Retrieve knowledge. Keep each chunk once and note which lookup found it.
    chunks, retrieval_log = {}, []
    for query in knowledge_queries(request):
        results = await meko.search_knowledge(conversation_id, query)
        retrieval_log.append({"query": query, "chunk_ids": [r["id"] for r in results]})
        for result in results:
            chunks.setdefault(result["id"], result)
    chunk_list = list(chunks.values())

    memory_query = f"{request.get('requester')} requested from {request.get('vendor')}"
    memories = await meko.search_memory(conversation_id, memory_query, limit=200)

    # Arithmetic and lookups are done in code and recorded with their sources.
    facts = compute_facts(request, chunk_list, memories)
    verified = code_checks(facts)
    related_ids = {r["memory_id"] for r in
                   facts.get("earlier_requests_same_requester_and_vendor_within_7_days", [])}
    relevant_memories = [m for m in memories if isinstance(m, dict) and m.get("id") in related_ids]

    user_message = build_user_message(request, chunk_list, relevant_memories, facts, verified)
    response = await llm.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        tools=[DECISION_TOOL],
        tool_choice={"type": "tool", "name": "record_decision"},
        messages=[{"role": "user", "content": user_message}],
    )
    findings = next(b.input for b in response.content if b.type == "tool_use")
    decision = resolve(findings, verified)
    decision["tier"] = facts.get("tier", decision["tier"])
    decision["computed_facts"] = facts

    message = await meko.add_message(
        conversation_id,
        input_text=json.dumps(request),
        output_text=json.dumps(decision),
        reasoning=decision["explanation"],
        plan=[
            "Retrieve the policy rules and reference data from Meko knowledge.",
            "Search Meko memory for earlier requests by this requester to this vendor.",
            "Work out amounts, budget, vendor status and split-purchase sums in code.",
            "Check every rule, then apply reject rules before escalate rules.",
        ],
        metadata={
            "agent_role": "policy",
            "request_id": request_id,
            "decision": decision["decision"],
            "rules": decision["rules"],
            "knowledge_chunk_ids": list(chunks),
            "memories_searched": len(memories),
            "memories_used": sorted(related_ids),
            "model_overruled_on": [o["rule"] for o in decision["model_overruled_by_code_checks"]],
            "model": model,
        },
    )
    message_id = None
    if isinstance(message, dict):
        message_id = message.get("message_id") or message.get("id")

    await meko.track_tokens(
        conversation_id, model,
        response.usage.input_tokens, response.usage.output_tokens,
        message_id=message_id,
    )

    rules = ", ".join(decision["rules"]) or "no rules cited"
    await meko.add_memory(
        conversation_id,
        text=(
            f"Purchase request {request_id} dated {request.get('request_date')}: "
            f"{request.get('requester')} ({request.get('department')}) requested "
            f"${request.get('amount_usd', 0):,.2f} from {request.get('vendor')} for "
            f"{request.get('item')}. Decision: {decision['decision']} ({rules})."
        ),
        metadata={
            "request_id": request_id,
            "decision": decision["decision"],
            "requester": request.get("requester"),
            "vendor": request.get("vendor"),
            "amount_usd": request.get("amount_usd"),
            "request_date": request.get("request_date"),
        },
    )

    return {
        "request_id": request_id,
        "conversation_id": conversation_id,
        "decision": decision,
        "retrieval": retrieval_log,
        "memories": [memory_text(m) for m in relevant_memories],
        "memories_searched": len(memories),
        "tokens": {
            "input": response.usage.input_tokens,
            "output": response.usage.output_tokens,
        },
        "model": model,
    }
