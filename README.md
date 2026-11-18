# procurement-audit

An auditable multi-agent procurement approval system, built on the Meko context
engine for ContextCon theme 07, "Show Your Work."

Three agents decide each purchase request, and every decision can be traced from
input to outcome:

1. **Intake** reads the request and extracts its fields.
2. **Policy** checks it against the procurement policy, vendor list, budgets, and
   past decisions.
3. **Approver** approves, rejects, or escalates, and records why.

Status: early setup. The policy, sample data, and reference solver are in place.
The agents are not built yet.

## Contents

| Path | What it is |
|---|---|
| `policy/procurement_policy.md` | The approval policy (PROC-001) the agents follow |
| `data/reference_data.json` | Department budgets, vendor list, pre-approved IT catalog |
| `data/purchase_requests.json` | 19 sample purchase requests |
| `data/expected_decisions.json` | Answer key for tests. Not given to the agents. |
| `tests/reference_solver.py` | Applies the policy in plain Python and checks the answer key |

## Check the sample data

Requires Python 3.9 or newer. From the repository root:

```
python tests/reference_solver.py
```

It prints one line per request and ends with `19 of 19 match the answer key`.

## Sample data

Harbor Ridge Distribution, its vendors, and its employees are fictional.

## Secrets

Keep the Meko API key in a `.env` file. `.env` is listed in `.gitignore` and must
never be committed.
