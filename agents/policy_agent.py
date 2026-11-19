"""Policy agent: decides one purchase request and records why.

For each request the agent:
  1. opens a Meko conversation, which becomes the trace for the decision;
  2. retrieves the policy rules and reference data from Meko knowledge;
  3. searches Meko memory for earlier requests by the same requester;
  4. asks the model to check every rule, using only what was retrieved,
     and works out the decision from those checks in code;
  5. records the decision, its reasoning and token use in the trace;
  6. stores a memory of the outcome for later decisions to find.
"""

import json

SYSTEM_PROMPT = """You are the Policy agent for procurement at Harbor Ridge Distribution.

Assess one purchase request. Use only the policy text, reference data and
memories given in the message. Do not rely on outside knowledge of procurement.

Check every rule in the policy, one at a time: R1 to R6 and E1 to E6. For each
rule, say whether its condition is met and give the specific fact that settles
it. Mark a rule as applying only when its condition is fully met. A rule you
considered and ruled out does not apply.

A vendor that does not appear in the Approved Vendor List in the context is
not on the list. Treat a blank or missing field as missing.

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


def resolve(findings):
    """Turn the model's rule checks into a decision, in the policy's order."""
    checks = {c["rule"]: c for c in findings["rule_checks"] if c["rule"] in RULE_IDS}
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
    return {
        "decision": decision,
        "rules": rules,
        "reviewers": reviewers,
        "tier": findings["tier"],
        "facts_used": [f"{rule}: {checks[rule]['evidence']}" for rule in rules],
        "explanation": findings["explanation"],
        "rule_checks": [checks[rule] for rule in RULE_IDS if rule in checks],
        "rules_not_checked": [rule for rule in RULE_IDS if rule not in checks],
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


def build_user_message(request, chunks, memories):
    parts = ["PURCHASE REQUEST", json.dumps(request, indent=2), "", "RETRIEVED POLICY AND REFERENCE DATA"]
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

    memory_query = (
        f"purchase requests from {request.get('requester')} to {request.get('vendor')}"
    )
    memories = await meko.search_memory(conversation_id, memory_query)

    user_message = build_user_message(request, chunk_list, memories)
    response = await llm.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        tools=[DECISION_TOOL],
        tool_choice={"type": "tool", "name": "record_decision"},
        messages=[{"role": "user", "content": user_message}],
    )
    findings = next(b.input for b in response.content if b.type == "tool_use")
    decision = resolve(findings)

    message = await meko.add_message(
        conversation_id,
        input_text=json.dumps(request),
        output_text=json.dumps(decision),
        reasoning=decision["explanation"],
        plan=[
            "Retrieve the policy rules and reference data from Meko knowledge.",
            "Search Meko memory for earlier requests by this requester to this vendor.",
            "Check every rule, then apply reject rules before escalate rules.",
        ],
        metadata={
            "agent_role": "policy",
            "request_id": request_id,
            "decision": decision["decision"],
            "rules": decision["rules"],
            "knowledge_chunk_ids": list(chunks),
            "memories_considered": len(memories),
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
        metadata={"request_id": request_id, "decision": decision["decision"]},
    )

    return {
        "request_id": request_id,
        "conversation_id": conversation_id,
        "decision": decision,
        "retrieval": retrieval_log,
        "memories": [memory_text(m) for m in memories],
        "tokens": {
            "input": response.usage.input_tokens,
            "output": response.usage.output_tokens,
        },
        "model": model,
    }
