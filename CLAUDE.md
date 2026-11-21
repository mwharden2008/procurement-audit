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
| `tests/test_policy_agent_offline.py` | Offline tests of the three-agent flow, Meko and the model faked (21 tests) |
| `agents/meko_client.py` | MCP client for Meko (streamable HTTP, Bearer API key, `mcp` 2.x) |
| `agents/workflow.py` | Runs Intake, Policy and Approver for one request in one Meko conversation |
| `agents/intake_agent.py` | Intake agent (step 1): opens the trace, checks and extracts the request fields |
| `agents/policy_agent.py` | Policy agent (step 2): retrieval, facts, code checks, model call, rule checks |
| `agents/approver_agent.py` | Approver agent (step 3): final decision, reviewers, explanation, memory |
| `agents/rules.py` | Resolve logic: `combine_checks` (Policy), `final_outcome` and `explain` (Approver), `resolve` |
| `agents/facts.py` | Arithmetic and lookups done in code, vendor-list completeness, `code_checks` verdicts per rule |
| `run_one.py` | Decide one request: `python run_one.py PR-004` |
| `run_all.py` | Decide all 19 in date order; skips decided ones; `--fresh` redoes all |
| `runs/` | One JSON record per decided request |

## How a decision is made

Three agents share one Meko conversation, which is the trace. Each records its
own step with `conversation_add_message`; the metadata carries `agent_role`
(intake, policy, approver), `step` (1 to 3) and `request_id`. All three use the
same Meko agent ID, `procurement_audit`, so Policy finds the memories Approver writes.

**Intake (step 1), code only**
1. `conversation_create` opens the conversation.
2. Trims text, reads the amount as a number and quotes as a whole number, and
   lists blank required fields for Policy to rule on under R1. It stops the run
   (`IntakeError`) only if the request cannot be read, such as a non-numeric amount.

**Policy (step 2)**
3. `knowledgebase_search` retrieves policy and reference data (about 8 lookups).
4. `memory_search` (limit 200) finds earlier requests; code filters them to the
   same requester and vendor using metadata stored with each decision memory.
5. `facts.compute_facts` works out tier, threshold comparisons, department budget,
   vendor status, catalog membership and split-purchase sums. Budget and vendor
   status are parsed from the retrieved chunk text, with the chunk ID kept.
6. If the vendor is not found, `facts.vendor_list` reassembles the Approved
   Vendor List from the retrieved chunks (Meko splits it in two overlapping
   chunks). It is complete only if the list's start and closing bracket were
   both retrieved and each piece overlaps the one before; no vendor count is
   hard-coded. Complete: code marks R2 as applying. Incomplete: Policy records a
   failed step and raises `IncompleteReferenceData` before any model call, so the
   request is not decided and `run_all.py` retries it.
7. `facts.code_checks` gives a verdict for every rule those facts settle. Only R6
   and E5 are always left to the model.
8. The model (Claude Haiku 5.5 through the Anthropic API) checks all 12 rules.
   `rules.combine_checks` merges them with the code checks; where they disagree
   the code verdict wins and the disagreement is saved under
   `model_overruled_by_code_checks`. `track_token_usage` is recorded on this step.

**Approver (step 3), code only**
9. `rules.final_outcome` applies reject-before-escalate and names the reviewers.
10. `rules.explain` writes the plain-language explanation from the final decision
    and the evidence for its deciding rules, so the two cannot disagree. The
    model's draft explanation stays in the Policy step of the trace but is not used.
11. `memory_add` stores a memory of the outcome with structured metadata.

## Meko

- Datapack: `procurement-audit`, ID `06edb990-0f4d-4572-a438-378c0d7d07c9`.
- Knowledge base holds `procurement_policy.md` and `reference_data.json`.
- Meko's indexer drops text in backticks, so the policy uses plain quoted words.
- Meko also extracts its own memories from each conversation turn. Those have no
  `request_id` metadata and the code ignores them.
- Memory from earlier runs is still in the datapack, including some wrong
  decisions. The code keeps the newest memory per request ID. A clean reset of
  memory before the final demo run would be worth doing; ask Michael first.

## Status on November 21, 2026

- Setup is complete: Meko connected, datapack loaded, repo public, API billing on.
- Live results: run 1 scored 16 of 19, run 2 15 of 19. Policy agent with code
  checks: 19 of 19 (commit f9d1615).
- Three agents added (Intake, Policy, Approver, one trace). First live run: 18 of
  19. PR-005 came out APPROVE because the model marked R2 as not applying for an
  unknown vendor while its own evidence said R2 applies.
- Fix: code now settles R2 for an unknown vendor when the whole vendor list was
  retrieved (fails the request otherwise), and the Approver writes the explanation
  from the final decision. Offline tests 21 of 21. **Live run with `--fresh`: 19
  of 19**, 98,111 input and 14,885 output tokens, no model verdicts overruled, every
  explanation matching its decision.
- Note: an inspection conversation titled "Chunk inspection (not a decision)" was
  opened in Meko on November 21 to look at how the vendor list is chunked.

## What is left to build

1. ~~Get the Policy agent to 19 of 19 live.~~ Done.
2. ~~Add the Intake and Approver agents so three agents share one trace.~~ Done.
3. "Explain this decision" page for a non-technical reader (Streamlit is the plan).
4. Audit report generated from the trace data.
5. Replay or resume of a failed run. `run_all.py` already resumes and retries a
   request that fails on incomplete reference data; a per-step replay from the
   Meko trace would be stronger.
6. Baseline measurement with and without Meko (tokens and answer quality).
7. README with full setup instructions, then the demo video.
8. Open gap: if the department budget or IT catalog is not retrieved, R3 or E4 is
   still left to the model rather than failing the request like the vendor list.

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
