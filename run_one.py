"""Decide one purchase request with the Policy agent.

Usage:  python run_one.py PR-004
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from agents.meko_client import connect
from agents.policy_agent import decide

ROOT = Path(__file__).resolve().parent
AGENT_ID = "procurement_audit"


def require(name):
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"Missing {name}. Add it to the .env file (see .env.example).")
    return value


async def main(request_id):
    load_dotenv(ROOT / ".env", override=True)
    meko_key = require("MEKO_API_KEY")
    datapack_id = require("MEKO_DATAPACK_ID")
    require("ANTHROPIC_API_KEY")
    model = os.environ.get("MODEL", "claude-haiku-5-5")

    requests = json.loads((ROOT / "data/purchase_requests.json").read_text(encoding="utf-8"))
    request = next((r for r in requests if r["request_id"] == request_id), None)
    if request is None:
        sys.exit(f"No request with ID {request_id} in data/purchase_requests.json.")

    llm = AsyncAnthropic()
    async with connect(meko_key, datapack_id, AGENT_ID) as meko:
        record = await decide(request, meko, llm, model)

    runs = ROOT / "runs"
    runs.mkdir(exist_ok=True)
    (runs / f"{request_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

    decision = record["decision"]
    print(f"\n{request_id}: {decision['decision']}  rules: {', '.join(decision['rules']) or 'none'}")
    if decision["reviewers"]:
        print(f"Reviewers: {', '.join(decision['reviewers'])}")
    print(f"\n{decision['explanation']}\n")
    print("Facts used:")
    for fact in decision["facts_used"]:
        print(f"  - {fact}")
    print(f"\nTokens: {record['tokens']['input']} in, {record['tokens']['output']} out ({model})")
    print(f"Meko conversation ID: {record['conversation_id']}")
    print(f"Saved to runs/{request_id}.json")

    # The answer key is read only after the decision, to report the comparison.
    expected = {d["request_id"]: d for d in json.loads(
        (ROOT / "data/expected_decisions.json").read_text(encoding="utf-8"))["decisions"]}
    want = expected.get(request_id)
    if want:
        match = (decision["decision"] == want["decision"]
                 and sorted(decision["rules"]) == sorted(want["rules"]))
        print(f"Answer key: {want['decision']} {want['rules']} -> {'MATCH' if match else 'DIFFERENT'}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python run_one.py PR-004")
    asyncio.run(main(sys.argv[1]))
