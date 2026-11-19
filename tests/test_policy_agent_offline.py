"""Offline test of the Policy agent's flow, with Meko and the model faked.

Checks that one decision makes the expected Meko calls in order and that the
record it returns is complete. It makes no network calls and needs no keys.

Run from the repository root:  python -m pytest tests/test_policy_agent_offline.py
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

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
        return [{"id": f"chunk-{len(query) % 3}", "chunk_text": f"text for {query}"}]

    async def search_memory(self, conversation_id, query, limit=10):
        self.calls.append("search_memory")
        return [{"memory": "PR-013: Daniel Okafor requested $900.00 from Keystone Safety Gear."}]

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
