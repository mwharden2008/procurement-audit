# Harbor Ridge Distribution: Procurement Approval Policy

**Policy ID:** PROC-001
**Effective:** October 1, 2026
**Applies to:** All purchase requests (PRs) submitted by employees
**Owner:** Procurement Manager

> Harbor Ridge Distribution is a fictional company. This policy, its vendors, and its
> employees are invented sample data for the ContextCon hackathon project.

## 1. Purpose

This policy sets the rules for deciding every purchase request. Each request ends in
exactly one of three decisions:

- **APPROVE**: the purchase may proceed.
- **REJECT**: the purchase may not proceed as submitted. The requester may fix the
  problem and resubmit.
- **ESCALATE**: the request is sent to a named human reviewer. The agent does not decide.

Every decision must cite the rule IDs that produced it.

## 2. Required information

A purchase request must include all of the following: requester, department, vendor,
item description, category, amount in USD, request date, and a business justification.

## 3. Approval tiers

The tier is set by the request amount.

| Tier | Amount (USD) | Extra requirements |
|---|---|---|
| T1 | Under $1,000 | None |
| T2 | $1,000 to $9,999.99 | Manager sign-off |
| T3 | $10,000 to $49,999.99 | Manager sign-off and three competitive quotes |
| T4 | $50,000 and over | Manager sign-off, three competitive quotes, and Finance Director review |

## 4. Reject rules

A request is rejected if any of these rules applies.

- **R1. Incomplete request.** Any item of required information in section 2 is missing
  or blank.
- **R2. Vendor not eligible.** The vendor is not on the Approved Vendor List, or its
  status is "suspended".
- **R3. Over budget.** The amount is greater than the department's remaining budget for
  the quarter.
- **R4. Missing manager sign-off.** The amount is $1,000 or more and no manager
  sign-off is recorded.
- **R5. Missing quotes.** The amount is $10,000 or more and fewer than three quotes are
  attached. This rule does not apply when a sole-source justification is attached
  (see E2).
- **R6. Prohibited item.** The request is for gift cards, alcohol, or items for
  personal use.

## 5. Escalate rules

A request that is not rejected is escalated if any of these rules applies.

| Rule | Condition | Reviewer |
|---|---|---|
| **E1. High value** | The amount is $50,000 or more. | Finance Director |
| **E2. Sole source** | The amount is $10,000 or more and a sole-source justification is attached in place of three quotes. | Procurement Manager |
| **E3. Vendor on probation** | The vendor's status is "probation" and the amount is more than $2,500. | Procurement Manager |
| **E4. Non-catalog IT** | The category is IT hardware or software and the item is not in the Pre-Approved IT Catalog. | IT Security |
| **E5. Conflict of interest** | The requester has declared a personal or financial relationship with the vendor. | Compliance Officer |
| **E6. Possible split purchase** | The same requester submits two or more requests to the same vendor within 7 calendar days, and their combined amount falls in a higher tier than each request does alone. The later request is escalated. | Procurement Manager |

## 6. Order of evaluation

1. Check every reject rule (R1 to R6). If one or more applies, the decision is
   **REJECT**. Cite every reject rule that applies.
2. Otherwise, check every escalate rule (E1 to E6). If one or more applies, the
   decision is **ESCALATE**. Cite every escalate rule that applies and name each
   reviewer.
3. Otherwise, the decision is **APPROVE**.

Reject rules take priority over escalate rules. A request that is both over budget and
high value is rejected, not escalated.

## 7. Budget checks

Each department has a remaining budget for the current quarter, listed in the reference
data. A request is within budget when its amount is less than or equal to that figure.

## 8. Decision record

Every decision must record:

- the request ID and the decision;
- the rule IDs that applied;
- the facts used, including vendor status, remaining budget, tier, and any earlier
  requests considered under E6;
- a plain-language explanation that a person outside Procurement can follow;
- the reviewer, when the decision is ESCALATE.

## Appendix A. Pre-Approved IT Catalog

IT hardware and software on this list do not trigger E4.

| Item | Vendor |
|---|---|
| Corvid C14 standard laptop | Corvid Systems |
| Corvid 27-inch monitor | Corvid Systems |
| Corvid USB-C docking station | Corvid Systems |
| Lanternsoft Office Suite license | Lanternsoft |

## Appendix B. Vendor statuses

| Status | Meaning |
|---|---|
| "approved" | Eligible for all purchases. |
| "probation" | Eligible, but requests over $2,500 are escalated (E3). |
| "suspended" | Not eligible. Requests are rejected (R2). |

The current Approved Vendor List and department budgets are kept in
data/reference_data.json.
