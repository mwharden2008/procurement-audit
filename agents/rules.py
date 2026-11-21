"""How rule checks become a decision under policy PROC-001.

The work is split between two agents:
  - the Policy agent calls `combine_checks` to merge the model's rule checks
    with the code checks (the code verdict wins where they disagree);
  - the Approver agent calls `final_outcome` to apply reject-before-escalate,
    name the reviewers and write the explanation from the final decision.

`resolve` runs both halves in one call and gives the same result.
"""

RULE_IDS = ["R1", "R2", "R3", "R4", "R5", "R6", "E1", "E2", "E3", "E4", "E5", "E6"]
REVIEWERS = {
    "E1": "Finance Director", "E2": "Procurement Manager",
    "E3": "Procurement Manager", "E4": "IT Security",
    "E5": "Compliance Officer", "E6": "Procurement Manager",
}


def combine_checks(findings, verified=None):
    """Merge the model's rule checks with the code's verdicts.

    `verified` holds the code's verdicts for rules the computed facts settle.
    Where the model disagrees with one, the code's verdict is used and the
    disagreement is recorded, so an auditor can see both.
    Returns (checks by rule, list of overrides).
    """
    verified = verified or {}
    model = {c["rule"]: c for c in findings["rule_checks"] if c["rule"] in RULE_IDS}
    checks, overrides = {}, []
    for rule in RULE_IDS:
        if rule in verified:
            said = model.get(rule, {}).get("applies")
            if said is not None and said != verified[rule]["applies"]:
                overrides.append({
                    "rule": rule, "model_said": said, "code_check_says": verified[rule]["applies"],
                    "model_evidence": model[rule]["evidence"], "reason": verified[rule]["reason"],
                })
            checks[rule] = {"rule": rule, "applies": verified[rule]["applies"],
                            "evidence": verified[rule]["reason"], "decided_by": "code check"}
        elif rule in model:
            checks[rule] = {**model[rule], "decided_by": "model"}
    return checks, overrides


REVIEWER_NAMES = {"IT Security": "the IT Security team"}


def sentence(text):
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def explain(decision, rules, reviewers, checks):
    """Plain-language explanation built from the final decision itself.

    The first sentence states the outcome; the rest give the evidence for each
    rule that decided it. Because it is built from the decision, it cannot say
    something different from the decision.
    """
    if decision == "REJECT":
        opening = "This request is rejected."
        evidence = [checks[rule]["evidence"] for rule in rules]
    elif decision == "ESCALATE":
        names = [REVIEWER_NAMES.get(r, f"the {r}") for r in reviewers]
        opening = (f"This request is not rejected, but it must be reviewed by "
                   f"{' and '.join(names)} before it can go ahead.")
        evidence = [checks[rule]["evidence"] for rule in rules]
    else:
        opening = "This request is approved. It meets every rule in the procurement policy."
        evidence = [checks[rule]["evidence"] for rule in ("R2", "R3", "R4") if rule in checks]
    return " ".join([opening] + [sentence(e) for e in evidence])


def final_outcome(checks, overrides, tier):
    """Apply reject-before-escalate and write the decision record."""
    applied = [rule for rule in RULE_IDS if checks.get(rule, {}).get("applies")]
    reject = [rule for rule in applied if rule.startswith("R")]
    escalate = [rule for rule in applied if rule.startswith("E")]
    if reject:
        decision, rules = "REJECT", reject
    elif escalate:
        decision, rules = "ESCALATE", escalate
    else:
        decision, rules = "APPROVE", []
    reviewers = sorted({REVIEWERS[rule] for rule in rules if rule in REVIEWERS})

    return {
        "decision": decision,
        "rules": rules,
        "reviewers": reviewers,
        "tier": tier,
        "facts_used": [f"{rule}: {checks[rule]['evidence']}" for rule in rules],
        "explanation": explain(decision, rules, reviewers, checks),
        "rule_checks": [checks[rule] for rule in RULE_IDS if rule in checks],
        "rules_not_checked": [rule for rule in RULE_IDS if rule not in checks],
        "model_overruled_by_code_checks": overrides,
    }


def resolve(findings, verified=None):
    """Turn the model's rule checks into a decision, in the policy's order."""
    checks, overrides = combine_checks(findings, verified)
    return final_outcome(checks, overrides, findings["tier"])
