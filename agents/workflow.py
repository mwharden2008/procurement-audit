"""Runs the three agents for one purchase request, in one Meko conversation.

  1. Intake   opens the conversation, checks the request and extracts its fields.
  2. Policy   retrieves policy and reference data, checks every rule.
  3. Approver records the final decision, the reviewers, the explanation and a memory.

Each agent records its own step in the conversation, with its role in the
message metadata, so the trace shows who did what.
"""

from agents import approver_agent, intake_agent, policy_agent


async def decide(request, meko, llm, model):
    """Decide one request and write its trace to Meko. Returns a record dict."""
    intake = await intake_agent.run(request, meko)
    conversation_id = intake["conversation_id"]
    fields = intake["fields"]

    policy = await policy_agent.run(fields, meko, llm, model, conversation_id)
    decision, approver_message_id = await approver_agent.run(fields, policy, meko, conversation_id)

    return {
        "request_id": fields["request_id"],
        "conversation_id": conversation_id,
        "decision": decision,
        "steps": [
            {"step": 1, "agent_role": intake_agent.ROLE, "message_id": intake["message_id"],
             "status": intake["status"], "summary": intake["summary"],
             "missing_required_fields": intake["missing_required_fields"]},
            {"step": 2, "agent_role": policy_agent.ROLE, "message_id": policy["message_id"],
             "rules_that_apply": [c["rule"] for c in policy["rule_checks"].values() if c["applies"]],
             "model_overruled_on": [o["rule"] for o in policy["model_overruled_by_code_checks"]]},
            {"step": 3, "agent_role": approver_agent.ROLE, "message_id": approver_message_id,
             "decision": decision["decision"], "rules": decision["rules"],
             "reviewers": decision["reviewers"]},
        ],
        "retrieval": policy["retrieval"],
        "memories": policy["memories"],
        "memories_searched": policy["memories_searched"],
        "tokens": policy["tokens"],
        "model": model,
    }
