"""Policy agent: checks one purchase request against every rule.

It is the second of three agents. It works in the Meko conversation the
Intake agent opened, on the fields Intake extracted. It:
  1. retrieves the policy rules and reference data from Meko knowledge;
  2. searches Meko memory for earlier requests by the same requester,
     and works out amounts, budget, vendor status and sums in code;
  3. asks the model to check every rule, using only what was retrieved;
  4. merges the model's checks with the code checks (code wins on a
     disagreement, and the disagreement is kept);
  5. records its rule checks and token use as its own step in the trace.

If the reference data a rule needs was not retrieved in full (the vendor
list for R2, the department budget for R3, the IT catalog for E4), it
records a failed step and stops, with no model call, so the request is never
decided on partial data and can be retried.

The Approver agent turns these checks into the final decision.
"""

import json

from agents.facts import (IncompleteReferenceData, code_checks, compute_facts,
                          require_complete_reference_data)
from agents.intake_agent import message_id_of
from agents.rules import RULE_IDS, combine_checks

ROLE = "policy"

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


async def run(request, meko, llm, model, conversation_id):
    """Check every rule for one request and record the Policy step.

    `request` holds the fields the Intake agent extracted.
    """
    request_id = request["request_id"]

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
    try:
        require_complete_reference_data(facts)
    except IncompleteReferenceData as error:
        await meko.add_message(
            conversation_id,
            input_text=json.dumps(request),
            output_text=json.dumps({"status": "failed", "error": str(error),
                                    "computed_facts": facts}),
            reasoning=str(error),
            metadata={"agent_role": ROLE, "step": 2, "request_id": request_id,
                      "status": "failed", "knowledge_chunk_ids": list(chunks)},
        )
        raise
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
    checks, overrides = combine_checks(findings, verified)
    result = {
        "rule_checks": checks,
        "model_overruled_by_code_checks": overrides,
        "model_draft_explanation": findings["explanation"],
        "tier": facts.get("tier", findings["tier"]),
        "computed_facts": facts,
    }

    applying = [rule for rule in RULE_IDS if checks.get(rule, {}).get("applies")]
    message = await meko.add_message(
        conversation_id,
        input_text=json.dumps(request),
        output_text=json.dumps({**result, "rule_checks": list(checks.values())}),
        reasoning=(f"Rules that apply: {', '.join(applying) or 'none'}. "
                   f"Rules where a code check overruled the model: "
                   f"{', '.join(o['rule'] for o in overrides) or 'none'}."),
        plan=[
            "Retrieve the policy rules and reference data from Meko knowledge.",
            "Search Meko memory for earlier requests by this requester to this vendor.",
            "Work out amounts, budget, vendor status and split-purchase sums in code.",
            "Check every rule, R1 to R6 and E1 to E6, and pass the checks to the Approver.",
        ],
        metadata={
            "agent_role": ROLE,
            "step": 2,
            "request_id": request_id,
            "rules_that_apply": applying,
            "knowledge_chunk_ids": list(chunks),
            "memories_searched": len(memories),
            "memories_used": sorted(related_ids),
            "model_overruled_on": [o["rule"] for o in overrides],
            "model": model,
        },
    )
    message_id = message_id_of(message)

    await meko.track_tokens(
        conversation_id, model,
        response.usage.input_tokens, response.usage.output_tokens,
        message_id=message_id,
    )

    result.update({
        "message_id": message_id,
        "retrieval": retrieval_log,
        "memories": [memory_text(m) for m in relevant_memories],
        "memories_searched": len(memories),
        "tokens": {"input": response.usage.input_tokens, "output": response.usage.output_tokens},
        "model": model,
    })
    return result
