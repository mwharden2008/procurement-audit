# procurement-audit: project handoff

Read this first. It carries over the context from the chat sessions where this
project was started (November 16 to 19, 2026).

## What this is

A solo entry by Michael Harden (GitHub: mwharden2008) for the ContextCon hackathon,
theme 07 "Show Your Work" (Best Auditability). Every project must use the Meko
context engine (by Yugabyte) as its context layer.

- **Deadline:** January 17, 2027, 11:59 PM PT.
- **Required deliverables:** public GitHub repo with setup instructions, and a demo
  video under 5 minutes.
- **Judging:** Use of Meko 30%, Impact 25%, Technical execution 20%, Innovation 15%,
  Presentation 10%.
- **Theme brief asks for:** a multi-agent system that makes real decisions; traces
  for 10 or more decisions; an "explain this decision" walkthrough for a
  non-technical reader; an audit report generated from trace data; replay or resume
  of a failed workflow (encouraged). The judges' test: someone who has never seen
  the system can explain one decision from its trace within 2 minutes.

The domain is a procurement approval workflow for a fictional company, Harbor Ridge
Distribution. All vendors, employees and requests are invented sample data.

## Layout

| Path | What it is |
|---|---|
| `policy/procurement_policy.md` | Policy PROC-001: reject rules R1 to R6, escalate rules E1 to E6, tiers T1 to T4 |
| `data/reference_data.json` | Department budgets, vendor list with statuses, pre-approved IT catalog |
| `data/purchase_requests.json` | 19 sample requests, PR-001 to PR-019 |
| `data/expected_decisions.json` | Answer key. Never give it to the agents or upload it to Meko. |
| `tests/reference_solver.py` | Plain-Python solver that checks the answer key (19 of 19) |
| `tests/test_policy_agent_offline.py` | Offline tests with Meko and the model faked (13 tests) |
| `agents/meko_client.py` | MCP client for Meko (streamable HTTP, Bearer API key, `mcp` 2.x) |
| `agents/facts.py` | Arithmetic and lookups done in code, plus `code_checks` verdicts per rule |
| `agents/policy_agent.py` | The Policy agent: retrieval, model call, `resolve`, trace writing |
| `run_one.py` | Decide one request: `python run_one.py PR-004` |
| `run_all.py` | Decide all 19 in date order; skips decided ones; `--fresh` redoes all |
| `runs/` | One JSON record per decided request |

## How a decision is made

1. `conversation_create` opens a Meko conversation, which is the trace.
2. `knowledgebase_search` retrieves policy and reference data (about 8 lookups).
3. `memory_search` (limit 200) finds earlier requests; code filters them to the
   same requester and vendor using metadata stored with each decision memory.
4. `facts.compute_facts` works out tier, threshold comparisons, department budget,
   vendor status, catalog membership and split-purchase sums. Budget and vendor
   status are parsed from the retrieved chunk text, with the chunk ID kept.
5. `facts.code_checks` gives a verdict for every rule those facts settle. R6, E5
   and "vendor not on the list" are left to the model.
6. The model (Claude Haiku 5.5 through the Anthropic API) checks all 12 rules and
   writes a plain-language explanation.
7. `policy_agent.resolve` applies reject-before-escalate in code. Where the model
   disagrees with a code check, the code verdict wins and the disagreement is saved
   under `model_overruled_by_code_checks`.
8. `conversation_add_message`, `track_token_usage` and `memory_add` record the
   decision, token use and a memory of the outcome.

## Meko

- Datapack: `procurement-audit`, ID `06edb990-0f4d-4572-a438-378c0d7d07c9`.
- Knowledge base holds `procurement_policy.md` and `reference_data.json`.
- Meko's indexer drops text in backticks, so the policy uses plain quoted words.
- Meko also extracts its own memories from each conversation turn. Those have no
  `request_id` metadata and the code ignores them.
- Memory from earlier runs is still in the datapack, including some wrong
  decisions. The code keeps the newest memory per request ID. A clean reset of
  memory before the final demo run would be worth doing; ask Michael first.

## Status on November 19, 2026

- Setup is complete: Meko connected, datapack loaded, repo public, API billing on.
- Live results so far: run 1 scored 16 of 19, run 2 scored 15 of 19.
- After run 2, four files were rewritten to add the code checks and a retry fix:
  `agents/facts.py`, `agents/policy_agent.py`,
  `tests/test_policy_agent_offline.py`, `run_all.py`. Offline tests pass (13 of
  13). **This version has not been run live yet.** On November 21 the four files
  were confirmed in place and pushed (commit 18dfa18).
- Next action: `python -m pytest tests/test_policy_agent_offline.py`, then
  `python run_all.py --fresh`, then review any request marked DIFFERENT using its
  record in `runs/`.

## What is left to build

1. Get the Policy agent to 19 of 19 live, then commit and push.
2. Add the Intake and Approver agents so three agents share one trace.
3. "Explain this decision" page for a non-technical reader (Streamlit is the plan).
4. Audit report generated from the trace data.
5. Replay or resume of a failed run. `run_all.py` already resumes; a per-step
   replay from the Meko trace would be stronger.
6. Baseline measurement with and without Meko (tokens and answer quality).
7. README with full setup instructions, then the demo video.

Rough plan: agents and traces by early December, viewer and report by
mid-December, buffer over the holidays, video and README in early January.

## Security: do this first

- `.env` holds `ANTHROPIC_API_KEY` and `MEKO_API_KEY`. It is in `.gitignore`. Never
  print it, open it in the editor, or commit it.
- **Both keys were visible in photos shared during setup and should be replaced.**
  Meko: Settings, API Keys. Claude: platform.claude.com, Keys. Then update `.env`.
- Confirm `.env` is not tracked: `git ls-files .env` must print nothing.

## Working with Michael

- He is comfortable with Python projects but newer to terminals, Git and Windows
  file paths. Give short numbered steps and exact commands he can copy and paste.
- Environment: Windows 11, PowerShell in VS Code, Python 3.14, Git 2.55,
  project at `C:\Users\mwhar\procurement-audit`.
- Report results plainly, including failures and anything not yet tested.
