"""Offline test of the Policy agent's flow, with Meko and the model faked.

Checks that one decision makes the expected Meko calls in order and that the
record it returns is complete. It makes no network calls and needs no keys.

Run from the repository root:  python -m pytest tests/test_policy_agent_offline.py
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from agents.facts import code_checks, compute_facts
from agents.policy_agent import RULE_IDS, decide, knowledge_queries, resolve

ROOT = Path(__file__).resolve().parent.parent


class FakeMeko:
    def __init__(self):
        self.calls = []

    async def start_conversation(self, title, metadata=None):
        self.calls.append("start_conversation")
        return "conv-1"

    async def search_knowledge(self, conversation_id, query, limit=4):
        self.calls.append("search_knowledge")
        reference = (ROOT / "data/reference_data.json").read_text(encoding="utf-8")
        return [{"id": "ref-1", "chunk_text": reference},
                {"id": f"chunk-{len(query) % 3}", "chunk_text": f"text for {query}"}]

    async def search_memory(self, conversation_id, query, limit=100):
        self.calls.append("search_memory")
        return [{
            "id": "mem-13", "created_at": "2026-11-19T19:13:50",
            "memory": "PR-013: Daniel Okafor requested $900.00 from Keystone Safety Gear.",
            "metadata": {"request_id": "PR-013", "requester": "Daniel Okafor",
                         "vendor": "Keystone Safety Gear", "amount_usd": 900.0,
                         "request_date": "2026-11-09"},
        }]

    async def add_message(self, conversation_id, input_text, output_text, **kwargs):
        self.calls.append("add_message")
        self.message = {"input": input_text, "output": output_text, **kwargs}
        return {"message_id": "msg-1"}

    async def track_tokens(self, conversation_id, model, input_tokens, output_tokens, message_id=None):
        self.calls.append("track_tokens")
        self.tokens = (input_tokens, output_tokens, message_id)

    async def add_memory(self, conversation_id, text, metadata=None):
        self.calls.append("add_memory")
        self.memory = text


class FakeModel:
    def __init__(self, decision):
        self.messages = self
        self.decision = decision

    async def create(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", input=self.decision)],
            usage=SimpleNamespace(input_tokens=1200, output_tokens=150),
        )


def load_request(request_id):
    requests = json.loads((ROOT / "data/purchase_requests.json").read_text(encoding="utf-8"))
    return next(r for r in requests if r["request_id"] == request_id)


def findings(applies, tier="T2", explanation="Explained."):
    """Model output in which only the rules in `applies` are marked as applying."""
    return {
        "rule_checks": [
            {"rule": rule, "applies": rule in applies, "evidence": f"evidence for {rule}"}
            for rule in RULE_IDS
        ],
        "tier": tier,
        "explanation": explanation,
    }


def test_decision_flow_records_a_full_trace():
    request = load_request("PR-004")
    meko, model = FakeMeko(), FakeModel(findings({"R2"}))

    record = asyncio.run(decide(request, meko, model, "test-model"))

    lookups = len(knowledge_queries(request))
    assert meko.calls == (
        ["start_conversation"] + ["search_knowledge"] * lookups
        + ["search_memory", "add_message", "track_tokens", "add_memory"]
    )
    decision = record["decision"]
    assert (decision["decision"], decision["rules"]) == ("REJECT", ["R2"])
    assert len(decision["rule_checks"]) == 12
    assert record["conversation_id"] == "conv-1"
    assert len(record["retrieval"]) == lookups
    assert meko.tokens == (1200, 150, "msg-1")
    assert "PR-004" in meko.memory and "REJECT (R2)" in meko.memory
    assert json.loads(meko.message["output"]) == decision


def test_model_sees_request_knowledge_and_memories():
    request = load_request("PR-014")
    meko, model = FakeMeko(), FakeModel(findings({"E6"}, tier="T1"))

    record = asyncio.run(decide(request, meko, model, "test-model"))

    prompt = model.request["messages"][0]["content"]
    assert "PR-014" in prompt
    assert "[K1]" in prompt
    assert "[M1] PR-013" in prompt
    assert "COMPUTED FACTS" in prompt
    facts = record["decision"]["computed_facts"]
    assert facts["combined_amount_usd"] == 1750.0
    assert facts["combined_tier_is_higher_than_each_request_alone"] is True
    assert model.request["tool_choice"] == {"type": "tool", "name": "record_decision"}
    assert record["decision"]["reviewers"] == ["Procurement Manager"]


def test_only_rules_marked_as_applying_are_cited():
    decision = resolve(findings({"R2"}))
    assert decision["rules"] == ["R2"]
    assert decision["facts_used"] == ["R2: evidence for R2"]


def test_reject_rules_take_priority_over_escalate_rules():
    decision = resolve(findings({"R3", "E1"}))
    assert (decision["decision"], decision["rules"], decision["reviewers"]) == ("REJECT", ["R3"], [])


def test_escalation_names_each_reviewer_once():
    decision = resolve(findings({"E2", "E4", "E6"}))
    assert decision["decision"] == "ESCALATE"
    assert decision["reviewers"] == ["IT Security", "Procurement Manager"]


def test_no_rules_applying_means_approve():
    decision = resolve(findings(set()))
    assert (decision["decision"], decision["rules"]) == ("APPROVE", [])


def test_a_rule_the_model_skipped_is_reported():
    partial = findings({"R2"})
    partial["rule_checks"] = partial["rule_checks"][:-1]
    assert resolve(partial)["rules_not_checked"] == ["E6"]


def test_it_requests_also_look_up_the_catalog():
    assert "Pre-Approved IT Catalog items" in knowledge_queries(load_request("PR-011"))
    assert "Pre-Approved IT Catalog items" not in knowledge_queries(load_request("PR-001"))


def reference_chunks():
    text = (ROOT / "data/reference_data.json").read_text(encoding="utf-8")
    return [{"id": "ref-1", "chunk_text": text}]


def decision_memory(request):
    return {
        "id": f"mem-{request['request_id']}", "created_at": "2026-11-19",
        "metadata": {k: request[k] for k in ("request_id", "requester", "vendor",
                                             "amount_usd", "request_date")},
    }


def test_computed_facts_agree_with_the_reference_solver_on_every_request():
    """The numeric rules, judged from computed facts alone, match the solver."""
    import reference_solver as solver

    reference = json.loads((ROOT / "data/reference_data.json").read_text(encoding="utf-8"))
    requests = sorted(
        json.loads((ROOT / "data/purchase_requests.json").read_text(encoding="utf-8")),
        key=lambda r: (r["request_date"], r["request_id"]))
    for position, request in enumerate(requests):
        earlier = requests[:position]
        facts = compute_facts(request, reference_chunks(), [decision_memory(r) for r in earlier])
        verdicts = code_checks(facts)
        got = {rule for rule, verdict in verdicts.items() if verdict["applies"]}
        decision, rules = solver.decide(request, reference, earlier)
        expected = set(rules) & set(verdicts)
        # The solver stops at reject rules, so compare each group separately.
        if decision == "REJECT":
            assert {r for r in got if r.startswith("R")} == expected, request["request_id"]
        else:
            assert got == expected, request["request_id"]


def test_code_check_overrules_the_model_and_records_it():
    request = load_request("PR-007")
    earlier = [decision_memory(load_request("PR-006"))]
    verdicts = code_checks(compute_facts(request, reference_chunks(), earlier))
    decision = resolve(findings({"E6"}, tier="T3"), verdicts)
    assert (decision["decision"], decision["rules"]) == ("APPROVE", [])
    overruled = decision["model_overruled_by_code_checks"]
    assert [o["rule"] for o in overruled] == ["E6"]
    assert overruled[0]["model_said"] is True
    assert decision["explanation"].startswith("This request is approved.")


def test_model_keeps_its_judgement_on_rules_the_code_cannot_settle():
    request = load_request("PR-017")
    verdicts = code_checks(compute_facts(request, reference_chunks(), []))
    assert "R6" not in verdicts and "E5" not in verdicts
    decision = resolve(findings({"R6"}, tier="T1"), verdicts)
    assert (decision["decision"], decision["rules"]) == ("REJECT", ["R6"])
    assert decision["model_overruled_by_code_checks"] == []


def test_later_and_unrelated_memories_are_ignored():
    request = load_request("PR-013")
    memories = [decision_memory(load_request(i)) for i in ("PR-014", "PR-002", "PR-013")]
    facts = compute_facts(request, reference_chunks(), memories)
    assert facts["earlier_requests_same_requester_and_vendor_within_7_days"] == []


def test_unknown_vendor_is_reported_as_not_found():
    facts = compute_facts(load_request("PR-005"), reference_chunks(), [])
    assert facts["vendor_status"].startswith("vendor not found among the 10 vendors")
