"""Decide every purchase request, in date order, with the Policy agent.

Requests that already have a record in runs/ are skipped, so a run that
stopped partway can be resumed by running the same command again.

Usage:
  python run_all.py           decide the requests that have no record yet
  python run_all.py --fresh   decide all of them again
"""

import asyncio
import json
import os
import sys

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from agents.meko_client import connect
from agents.policy_agent import decide
from run_one import AGENT_ID, ROOT, require


def describe(error):
    """Name the underlying error when it is wrapped in an exception group."""
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    return f"{type(error).__name__}: {error}"


def load_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


async def main(fresh):
    load_dotenv(ROOT / ".env", override=True)
    meko_key = require("MEKO_API_KEY")
    datapack_id = require("MEKO_DATAPACK_ID")
    require("ANTHROPIC_API_KEY")
    model = os.environ.get("MODEL", "claude-haiku-5-5")

    requests = sorted(load_json("data/purchase_requests.json"),
                      key=lambda r: (r["request_date"], r["request_id"]))
    runs = ROOT / "runs"
    runs.mkdir(exist_ok=True)

    llm = AsyncAnthropic()
    failed = []
    for request in requests:
        request_id = request["request_id"]
        record_path = runs / f"{request_id}.json"
        if record_path.exists() and not fresh:
            print(f"{request_id}  already decided, skipped")
            continue
        if record_path.exists():
            record_path.unlink()  # a fresh decision replaces the old record
        record = None
        for attempt in (1, 2):
            try:
                # One Meko connection per request, so a dropped connection
                # stops only that request.
                async with connect(meko_key, datapack_id, AGENT_ID) as meko:
                    record = await decide(request, meko, llm, model)
                break
            except Exception as error:  # keep going; the request can be retried
                print(f"{request_id}  attempt {attempt} failed: {describe(error)}")
        if record is None:
            failed.append(request_id)
            continue
        record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        decision = record["decision"]
        print(f"{request_id}  {decision['decision']:<8} {', '.join(decision['rules'])}")

    # Compare every saved record with the answer key.
    expected = {d["request_id"]: d for d in load_json("data/expected_decisions.json")["decisions"]}
    print("\nResults against the answer key")
    matched = decided = tokens_in = tokens_out = 0
    for request in requests:
        request_id = request["request_id"]
        record_path = runs / f"{request_id}.json"
        if not record_path.exists():
            print(f"  {request_id}  no record")
            continue
        record = json.loads(record_path.read_text(encoding="utf-8"))
        got, want = record["decision"], expected[request_id]
        ok = got["decision"] == want["decision"] and sorted(got["rules"]) == sorted(want["rules"])
        decided += 1
        matched += ok
        tokens_in += record["tokens"]["input"]
        tokens_out += record["tokens"]["output"]
        if not ok:
            print(f"  {request_id}  DIFFERENT: got {got['decision']} {got['rules']}, "
                  f"expected {want['decision']} {want['rules']}")
    print(f"\n{matched} of {decided} decided requests match the answer key "
          f"({len(requests)} requests in total)")
    print(f"Tokens across these records: {tokens_in} in, {tokens_out} out")
    if failed:
        print(f"Failed and not recorded: {', '.join(failed)}. Run the command again to retry them.")


if __name__ == "__main__":
    asyncio.run(main("--fresh" in sys.argv))
